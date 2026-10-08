"""阵列候选和完整二维尺寸验证：图像真值与独立解析几何分开。"""

import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from custom_nodes.connector_nodes.categories.array.backend.nodes.pin_array_locate import (
    handle_node as locate,
)
from custom_nodes.connector_nodes.categories.measurement.backend.nodes.measure import (
    handle_node as measure,
)
from tests.test_connector_nodes import request, source


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
@pytest.mark.parametrize(
    "condition", ["reference", "extra_pin", "missing_middle", "designed_empty"]
)
def test_explicit_candidate_bands_find_extras_and_keep_ids(family, condition):
    """正常排中不报多针；配方指定的空区中检出实际生成的多余针。"""
    image, layout, reference, _ = source(family, condition)
    rows = {p["row_id"] for p in layout["pins"]}
    bands = []
    for row in sorted(rows):
        positions = np.array(
            [p["center"] for p in layout["pins"] if p["row_id"] == row]
        )
        bands.append(
            dict(
                band_id=row,
                center=positions.mean(axis=0).tolist(),
                length=float(np.ptp(positions[:, 0]) + 60),
                sampling_type="normal",
            )
        )
    # 工程图配方的额外空区；不读取当前被测图真值来决定范围。
    bands.append(
        dict(
            band_id="outside-row",
            center=[640.0, 156.0 if family == "single10_front" else 280.0],
            length=850.0,
            sampling_type="normal",
        )
    )
    layout["candidate_bands"] = bands
    if condition == "designed_empty":
        layout["pins"][4]["expected_present"] = False
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    output = locate(
        request(registry, dict(layout=layout, pose_mode="fixed"), {"image": payload})
    )
    assert [p["pin_id"] for p in output["pins"]["pins"]] == [
        p["pin_id"] for p in layout["pins"]
    ]
    assert output["summary"]["value"]["extra_search_performed"] is True
    assert all(i["valid"] for i in output["checks"]["items"])
    expected = 1 if condition == "extra_pin" else 0
    assert len(output["pins"]["unassigned_points"]) == expected
    assert (
        sum(
            i["value"]
            for i in output["checks"]["items"]
            if i["item_id"].startswith("extra:")
        )
        == expected
    )


def test_named_visible_endpoints_measure_length():
    """由真实渲染原图提取针尖与壳体入口，而不是名义总长或包围框。"""
    image, layout, reference, _ = source("single10_front")
    layout["types"].append(
        dict(
            type_id="axial",
            search_length=240.0,
            band_width=6.0,
            scan_lines=9,
            angle_degrees=90.0,
            min_width=180.0,
            max_width=220.0,
            gradient_threshold=0.04,
        )
    )
    layout["pins"][0]["endpoint_pairs"] = [
        dict(first_id="tip", second_id="root", sampling_type="axial")
    ]
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    output = locate(
        request(registry, dict(layout=layout, pose_mode="fixed"), {"image": payload})
    )
    result = measure(
        request(
            registry,
            {
                "items": [
                    dict(
                        item_id="visible_length",
                        kind="length",
                        pin_a="R1P01",
                        pin_b="R1P01",
                        feature_a="R1P01:tip",
                        feature_b="R1P01:root",
                        direction=[0.0, 1.0],
                    )
                ]
            },
            {"pins": output["pins"], "features": output["features"]},
        )
    )
    item = result["measurements"]["items"][0]
    assert item["valid"], item
    # Blender 生成模型的外露段为 6 mm；光栅边界允许 1 像素偏差。
    assert item["value"] == pytest.approx(
        6 * reference["camera"]["pixels_per_mm"], abs=1.0
    )


def test_candidate_band_uses_same_section_within_observed_edges():
    """搜索带相对名义中心偏移时，有限观测区内的同一 PIN 不误报为额外针。"""
    image, layout, _, _ = source("single10_front")
    positions = np.asarray([p["center"] for p in layout["pins"]])
    center = positions.mean(axis=0) + [0, 2]
    layout["candidate_bands"] = [
        dict(
            band_id="offset-band",
            center=center.tolist(),
            length=float(np.ptp(positions[:, 0]) + 60),
            sampling_type="normal",
        )
    ]
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    output = locate(
        request(registry, dict(layout=layout, pose_mode="fixed"), {"image": payload})
    )
    assert output["checks"]["items"][-1]["value"] == 0
    assert output["pins"]["unassigned_points"] == []


def test_width_gap_pitch_total_offset_angle_from_observed_image():
    """同一观测支持各尺寸定义，公差判断仍不进入行业节点。"""
    image, layout, reference, _ = source("single10_front")
    registry = ExecutionImageRegistry()
    payload = register_image_matrix(request(registry), image_matrix=image)
    output = locate(
        request(registry, dict(layout=layout, pose_mode="fixed"), {"image": payload})
    )
    result = measure(
        request(
            registry,
            {
                "items": [
                    dict(
                        item_id="width",
                        kind="width",
                        pin_a="R1P01",
                        section=layout["pins"][0]["center"][1],
                    ),
                    dict(
                        item_id="gap",
                        kind="gap",
                        pin_a="R1P01",
                        pin_b="R1P02",
                        section=layout["pins"][0]["center"][1],
                    ),
                    dict(item_id="pitch", kind="pitch", pin_a="R1P01", pin_b="R1P02"),
                    dict(
                        item_id="total",
                        kind="total_pitch",
                        pin_a="R1P01",
                        pin_b="R1P10",
                    ),
                    dict(item_id="offset", kind="offset", pin_a="R1P01"),
                    dict(item_id="angle", kind="angle", pin_a="R1P01", pin_b="R1P02"),
                ]
            },
            {"pins": output["pins"], "features": output["features"]},
        )
    )
    values = {i["item_id"]: i for i in result["measurements"]["items"]}
    assert all(i["valid"] for i in values.values())
    scale = reference["camera"]["pixels_per_mm"]
    for name, expected in {
        "width": 0.64 * scale,
        "gap": 1.90 * scale,
        "pitch": 2.54 * scale,
        "total": 9 * 2.54 * scale,
        "offset": 0.0,
        "angle": 0.0,
    }.items():
        assert values[name]["value"] == pytest.approx(expected, abs=0.8), (
            name,
            values[name],
        )


def test_draw_measurement_labels_keep_units():
    """通用绘制节点支持显式物理单位，不再把毫米显示成像素距离。"""
    from custom_nodes.opencv_nodes.categories.render.backend.nodes.draw_measurements import (
        _measurement_label,
    )
    from backend.service.application.errors import InvalidRequestError

    assert (
        _measurement_label({"label": "W: 0.640 millimeter"}, "D", "distance_pixels")
        == "W: 0.640 millimeter"
    )
    assert (
        _measurement_label({"distance_pixels": 12.3}, "D", "distance_pixels")
        == "D=12.30"
    )
    with pytest.raises(InvalidRequestError):
        _measurement_label({"label": "a\nb"}, "D", "distance_pixels")
