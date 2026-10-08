"""通用数组级计量的数学、预算、位深及资源图片检查。"""

import json
from pathlib import Path
from threading import Event

import cv2
import numpy as np
import pytest

from custom_nodes.opencv_nodes.shared.backend.metrology import (
    EdgePairSettings,
    extract_edge_pair,
    fit_planar_calibration,
    map_points,
    measure_section,
    prepare_gray,
)


def test_subpixel_edge_pair_depth_and_readonly_input():
    """同一非整数边缘在 8/16 位和 float32 中保留强度与连续位置。"""
    x = np.arange(128, dtype=np.float32)
    profile = np.clip(x - 49.3 + 0.5, 0, 1) - np.clip(x - 70.7 + 0.5, 0, 1)
    image = np.repeat(profile[None], 64, axis=0)
    for dtype, scale in ((np.uint8, 255), (np.uint16, 65535), (np.float32, 1)):
        original = (image * scale).astype(dtype)
        before = original.copy()
        result = extract_edge_pair(
            prepare_gray(original), (60.0, 32.0), (1.0, 0.0), EdgePairSettings()
        )
        assert result["state"] == "found"
        left = measure_section(result["left"], (1.0, 0.0), 32.0)
        right = measure_section(result["right"], (1.0, 0.0), 32.0)
        assert abs(right[0] - left[0] - 21.4) < 0.3
        np.testing.assert_array_equal(original, before)


def test_dark_edges_and_invalid_image_and_scan():
    """极性相反、越界、空图与不支持位深均有明确行为。"""
    image = np.ones((64, 128), np.float32)
    image[:, 50:71] = 0
    assert (
        extract_edge_pair(
            image, (60.0, 32.0), (1.0, 0.0), EdgePairSettings(polarity="dark")
        )["state"]
        == "found"
    )
    assert (
        extract_edge_pair(image, (5.0, 32.0), (1.0, 0.0), EdgePairSettings())["state"]
        == "out_of_view"
    )
    assert (
        extract_edge_pair(
            np.zeros_like(image), (60.0, 32.0), (1.0, 0.0), EdgePairSettings()
        )["state"]
        == "not_found"
    )
    for image in (
        np.ones((5, 5), np.float64),
        np.full((5, 5), np.nan, np.float32),
        np.ones((5, 5, 2), np.uint8),
    ):
        with pytest.raises(ValueError):
            prepare_gray(image)
    with pytest.raises(ValueError):
        extract_edge_pair(
            np.zeros((64, 128), np.float32),
            (60.0, 32.0),
            (1.0, 0.0),
            EdgePairSettings(scan_lines=1000),
        )


def test_optional_diagnostics_are_bounded_and_do_not_change_geometry():
    """诊断复用同次采样，不改变测量；大窗口只限制显示点而不截断算法。"""
    image = np.zeros((100, 2200), np.float32)
    image[:, 1080:1120] = 1
    settings = EdgePairSettings(search_length=2048, sample_step=0.25, max_width=45)
    normal = extract_edge_pair(image, (1100, 50), (1, 0), settings)
    diagnostic = {}
    inspected = extract_edge_pair(
        image, (1100, 50), (1, 0), settings, diagnostics=diagnostic
    )
    assert inspected == normal
    assert len(diagnostic["distance_px"]) == 1024
    assert len(diagnostic["intensity"]) == len(diagnostic["gradient"]) == 1024
    assert len(diagnostic["observed_pairs"]) <= settings.scan_lines
    assert diagnostic["residual_px"] == normal["residual_px"]
    missing = {}
    result = extract_edge_pair(
        image * 0, (1100, 50), (1, 0), settings, diagnostics=missing
    )
    assert result["state"] == "not_found"
    assert missing["observed_pairs"] == []
    assert "residual_px" not in missing
    extract_edge_pair(image, (0, 0), (1, 0), settings, diagnostics=diagnostic)
    assert diagnostic == {}


def test_finite_section_does_not_extrapolate_and_projective_lengths():
    """有限边缘拒绝区间外截面；透视长度必须由变换后的点计算。"""
    assert measure_section([(10.0, 0.0), (10.0, 5.0)], (1.0, 0.0), 6.0) is None
    assert (
        measure_section([(10.0, 0.0), (10.0, 5.0), (20.0, 0.0)], (1.0, 0.0), 2.0)
        is None
    )
    matrix = [[1.0, 0, 0], [0, 1.0, 0], [0.01, 0, 1.0]]
    points = map_points([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]], matrix)
    assert not np.isclose(
        np.linalg.norm(points[1] - points[0]), np.linalg.norm(points[2] - points[1])
    )


@pytest.mark.parametrize("model", ["similarity", "affine", "homography"])
def test_planar_calibration_independent_holdout(model):
    """平面孔距场景复用标定函数，并使用未参与拟合的控制点。"""
    source = np.array(
        [[10, 10], [100, 10], [100, 100], [10, 100], [60, 40]], np.float64
    )
    validation = np.array([[30, 30], [80, 70]], np.float64)
    matrix = np.array([[0.1, -0.03, 2], [0.03, 0.1, 5], [0, 0, 1]], np.float64)
    if model == "affine":
        matrix[0, 1] = 0.01
    if model == "homography":
        matrix[2, 0] = 0.001
    result = fit_planar_calibration(
        source,
        map_points(source, matrix),
        validation,
        map_points(validation, matrix),
        model=model,
        image_size=(128, 128),
    )
    assert result.validation_max_error < 1e-5
    assert len(result.evidence.control_points) == len(source)
    assert len(result.evidence.validation_points) == len(validation)
    with pytest.raises(ValueError):
        fit_planar_calibration(
            source,
            map_points(source, matrix),
            source[:2],
            map_points(source[:2], matrix),
            model=model,
            image_size=(128, 128),
        )


def test_cancellation_callback_checked_between_scan_lines():
    """共享算法在扫描边界调用执行控制，不吞掉取消。"""
    event = Event()
    calls = []

    def check():
        calls.append(1)
        if len(calls) == 3:
            event.set()
        if event.is_set():
            raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        extract_edge_pair(
            np.zeros((64, 128), np.float32),
            (60.0, 32.0),
            (1.0, 0.0),
            EdgePairSettings(),
            check=check,
        )


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
def test_prepared_reference_images(family):
    """实际读取已生成的连接器原图；只用名义参考位置指定扫描带。"""
    root = (
        Path(__file__).resolve().parents[1]
        / "data/development/connector-inspection/synthetic-v1"
    )
    if not root.exists():
        pytest.skip("本机开发资源未生成；按资源文档生成后运行")
    image = cv2.imdecode(
        np.fromfile(root / "images" / f"{family}__reference.png", np.uint8),
        cv2.IMREAD_UNCHANGED,
    )
    truth = json.loads(
        (root / "truth" / f"{family}__reference.json").read_text(encoding="utf-8")
    )
    gray = prepare_gray(image)
    for pin in truth["pins"]:
        result = extract_edge_pair(
            gray,
            pin["nominal_center_image_px"],
            (1.0, 0.0),
            EdgePairSettings(gradient_threshold=0.015),
        )
        assert result["state"] == "found", pin["pin_id"]
        section = pin["nominal_center_image_px"][1]
        width = (
            measure_section(result["right"], (1.0, 0.0), section)[0]
            - measure_section(result["left"], (1.0, 0.0), section)[0]
        )
        expected = pin["width_mm"] * truth["camera"]["pixels_per_mm"]
        assert abs(width - expected) < 0.5, (pin["pin_id"], width, expected)
