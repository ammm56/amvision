"""计量强度编码和等价掩膜相关的独立数值回归。"""

import cv2
import numpy as np
import pytest

from custom_nodes.opencv_nodes.shared.backend.metrology.sampling import prepare_gray
from custom_nodes.opencv_nodes.shared.backend.metrology.localization import (
    _masked_correlation,
    _variant,
)


@pytest.mark.parametrize(
    "dtype,levels", [(np.uint8, 255), (np.uint16, 65535), (np.float32, 1)]
)
def test_explicit_srgb_preserves_input_and_linearizes_before_grayscale(dtype, levels):
    """独立公式检查颜色通道；默认行为不隐式转换，输入不被改写。"""
    image = (np.array([[[0.1, 0.5, 0.8], [0.0, 0.02, 1.0]]]) * levels).astype(dtype)
    original = image.copy()
    encoded = image.astype(np.float64) / levels
    linear = np.where(
        encoded <= 0.04045, encoded / 12.92, ((encoded + 0.055) / 1.055) ** 2.4
    )
    expected = linear @ np.array([0.114, 0.587, 0.299])
    np.testing.assert_allclose(
        prepare_gray(image, image_encoding="srgb"), expected, atol=2e-7
    )
    np.testing.assert_array_equal(image, original)
    np.testing.assert_array_equal(
        prepare_gray(image), prepare_gray(image, image_encoding="native")
    )
    with pytest.raises(ValueError):
        prepare_gray(image, image_encoding="automatic")


@pytest.mark.parametrize("angle", [0, 7, -11, 43])
def test_binary_mask_correlation_matches_opencv(angle):
    """不改变候选及评分定义，在独立随机图上与 OpenCV 通用实现比较。"""
    rng = np.random.default_rng(341)
    source = rng.uniform(0.1, 0.9, (128, 160)).astype(np.float32)
    template, _, mask = _variant(source[35:62, 45:92].copy(), angle)
    expected = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED, mask=mask)
    actual = _masked_correlation(source, template, mask)
    np.testing.assert_allclose(actual, expected, atol=3e-5)
    assert cv2.minMaxLoc(actual)[3] == cv2.minMaxLoc(expected)[3]


def test_constant_search_area_cannot_be_perfect_match():
    """近常量窗口没有可信相关证据，不因归一化浮点误差生成高分。"""
    rng = np.random.default_rng(9)
    template, _, mask = _variant(rng.uniform(0.1, 0.9, (20, 40)).astype(np.float32), 11)
    result = _masked_correlation(np.full((70, 90), 0.4, np.float32), template, mask)
    assert np.isfinite(result).all()
    assert result.max() < 0.75


def test_relative_gradient_tracks_exposure_with_absolute_noise_floor():
    """相对门限随强度变化，绝对底线仍拒绝低于噪声门限的条纹。"""
    from custom_nodes.opencv_nodes.shared.backend.metrology.sampling import (
        EdgePairSettings,
        extract_edge_pair,
    )

    image = np.zeros((64, 128), np.float32)
    image[:, 50:71] = 1
    settings = EdgePairSettings(
        gradient_threshold=0.005, relative_gradient_threshold=0.2
    )
    edges = []
    thresholds = []
    for exposure in (0.1, 0.4, 0.9):
        diagnostic = {}
        result = extract_edge_pair(
            image * exposure, (60, 32), (1, 0), settings, diagnostics=diagnostic
        )
        assert result["state"] == "found"
        edges.append(result["left"])
        thresholds.append(diagnostic["gradient_threshold_range"][0])
    np.testing.assert_allclose(edges, [edges[0]] * 3, atol=1e-5)
    assert thresholds[0] < thresholds[1] < thresholds[2]
    assert (
        extract_edge_pair(image * 0.0001, (60, 32), (1, 0), settings)["state"]
        == "not_found"
    )
    for value in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError):
            extract_edge_pair(
                image,
                (60, 32),
                (1, 0),
                EdgePairSettings(relative_gradient_threshold=value),
            )
    with pytest.raises(ValueError):
        prepare_gray(image, image_encoding=[])
