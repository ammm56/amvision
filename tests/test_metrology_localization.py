"""刚性定位的原点、歧义、预算以及独立参考图片检查。"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from custom_nodes.opencv_nodes.shared.backend.metrology import map_points, prepare_gray
from custom_nodes.opencv_nodes.shared.backend.metrology.localization import (
    RigidLocateSettings,
    locate_rigid,
)


def test_nonconnector_crop_anchor_not_found_and_multiple_instances():
    """不依赖 PIN 的不对称工件验证裁剪原点、锚点和多工件。"""
    ref = np.zeros((100, 120), np.float32)
    cv2.rectangle(ref, (25, 30), (64, 54), 0.8, -1)
    cv2.circle(ref, (27, 33), 7, 0.2, -1)
    settings = RigidLocateSettings(
        reference_id="generic-bracket",
        template_roi=(20, 20, 50, 40),
        anchor=(25.0, 30.0),
        angle_min=0.0,
        angle_max=0.0,
        minimum_score=0.85,
    )
    target = np.zeros((160, 200), np.float32)
    target[40:80, 70:120] = ref[20:60, 20:70]
    result = locate_rigid(target, ref, settings)
    assert result["state"] == "found"
    np.testing.assert_allclose(
        map_points([[25.0, 30.0]], result["matrix"]), [[75.0, 50.0]], atol=0.1
    )
    target[100:140, 10:60] = ref[20:60, 20:70]
    assert locate_rigid(target, ref, settings)["state"] == "ambiguous"
    assert locate_rigid(np.zeros_like(target), ref, settings)["state"] == "not_found"
    with pytest.raises(ValueError):
        RigidLocateSettings(
            **(settings.model_dump() | {"angle_max": 180.0, "angle_step": 0.1})
        )


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
@pytest.mark.parametrize(
    "condition", ["reference", "translate", "rotate_pos", "rotate_neg", "no_part"]
)
def test_prepared_image_pose(family, condition):
    """位姿来自图像匹配，验收真值仅用于核对，不注入检测器。"""
    root = (
        Path(__file__).resolve().parents[1]
        / "data/development/connector-inspection/synthetic-v1"
    )
    if not root.exists():
        pytest.skip("开发资源尚未生成")
    ref = json.loads(
        (root / "references" / f"{family}.json").read_text(encoding="utf-8")
    )
    image = prepare_gray(
        cv2.imdecode(
            np.fromfile(root / "images" / f"{family}__{condition}.png", np.uint8),
            cv2.IMREAD_COLOR,
        )
    )
    reference = prepare_gray(
        cv2.imdecode(np.fromfile(root / ref["image"], np.uint8), cv2.IMREAD_COLOR)
    )
    polygon = np.asarray(ref["template_roi_polygon_px"])
    low = np.floor(polygon.min(axis=0) - 5).astype(int)
    high = np.ceil(polygon.max(axis=0) + 5).astype(int)
    settings = RigidLocateSettings(
        reference_id=family,
        template_roi=(*low.tolist(), *(high - low).tolist()),
        anchor=ref["template_anchor_image_px"],
        minimum_score=0.75,
    )
    result = locate_rigid(image, reference, settings)
    if condition == "no_part":
        assert result["state"] == "not_found"
    else:
        assert result["state"] == "found", result
        original = json.loads((root / ref["truth"]).read_text(encoding="utf-8"))
        actual = json.loads(
            (root / "truth" / f"{family}__{condition}.json").read_text(encoding="utf-8")
        )
        points = map_points(
            [p["nominal_center_image_px"] for p in original["pins"]], result["matrix"]
        )
        expected = np.asarray([p["nominal_center_image_px"] for p in actual["pins"]])
        assert float(np.linalg.norm(points - expected, axis=1).max()) < 1.0, (
            condition,
            result,
        )
