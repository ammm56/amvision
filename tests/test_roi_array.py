"""首槽阵列的坐标、稳定关联、范围和取消边界。"""

from dataclasses import replace
import pytest

from backend.nodes.core_nodes.support.roi import (
    build_roi_payload,
    polygon_area,
    polygon_bbox_xyxy,
)
from backend.service.application.errors import InvalidRequestError
from scripts.validate_linescan_front_registration import request
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.roi_array import (
    handle_node,
)


def polygon(points, identifier="seed"):
    """测试的显式多边形。"""
    return build_roi_payload(
        roi_id=identifier,
        display_name=None,
        roi_kind="polygon",
        polygon_xy=points,
        bbox_xyxy=polygon_bbox_xyxy(points),
        area=polygon_area(points),
    )


def test_array_preserves_geometry_and_explicit_parent_offset():
    """非轴对齐阵列可逐点核对，首槽在父裁图内，输出恢复父图坐标。"""
    seed = polygon([[1, 2], [7, 2], [7, 4], [4, 4], [4, 8], [1, 8]])
    frame = polygon([[10, 20], [110, 20], [110, 120], [10, 120]], "tray")
    frame["roi_kind"] = "bbox"
    req = request(
        "geometry",
        "roi_array",
        {"roi": seed, "frame": frame},
        {
            "rows": 3,
            "columns": 6,
            "column_step_xy": [10, -1],
            "row_step_xy": [2, 20],
            "roi_id_prefix": "slot",
        },
    )
    # 负列 Y 位移需要将首槽向下放，不能通过静默裁剪掩盖越界。
    with pytest.raises(InvalidRequestError, match="超出"):
        handle_node(req)
    seed = polygon([[1, 8], [7, 8], [7, 10], [4, 10], [4, 14], [1, 14]])
    result = handle_node(replace(req, input_values={"roi": seed, "frame": frame}))
    items = result["rois"]["items"]
    assert len(items) == 18 and len({i["roi_id"] for i in items}) == 18
    assert items[-1]["roi_id"] == "slot-r03-c06"
    assert items[-1]["polygon_xy"][0] == [65, 63]
    assert items[0]["polygon_xy"][0] == [11, 28]
    assert seed["polygon_xy"][0] == [1, 8]


@pytest.mark.parametrize(
    "parameters",
    [
        {"rows": 0},
        {"rows": True},
        {"rows": 100, "columns": 100},
        {"columns": 2, "column_step_xy": [0, 0]},
        {"rows": 2, "columns": 2, "row_step_xy": [1, 0]},
        {"row_step_xy": [float("nan"), 0]},
        {"roi_id_prefix": " "},
    ],
)
def test_array_rejects_invalid_or_unbounded_parameters(parameters):
    """无效几何和过大阵列在生成前拒绝。"""
    with pytest.raises(InvalidRequestError):
        handle_node(
            request(
                "geometry",
                "roi_array",
                {"roi": polygon([[0, 0], [10, 0], [0, 10]])},
                parameters,
            )
        )


def test_frame_rejects_scaled_seed_image():
    """不能把已缩放首槽图的坐标静默当作父图坐标。"""
    seed = polygon([[0, 0], [10, 0], [0, 10]])
    seed["source_image"] = {"width": 50, "height": 50}
    frame = polygon([[0, 0], [100, 0], [100, 100], [0, 100]])
    frame["roi_kind"] = "bbox"
    with pytest.raises(InvalidRequestError, match="尺寸"):
        handle_node(request("geometry", "roi_array", {"roi": seed, "frame": frame}, {}))


def test_array_rejects_inconsistent_seed_and_nonfinite_frame():
    """不能让框选显示与实际阵列几何不一致，也不能把非有限值交给 floor。"""
    seed = polygon([[0, 0], [10, 0], [0, 10]])
    with pytest.raises(InvalidRequestError, match="不一致"):
        handle_node(
            request(
                "geometry",
                "roi_array",
                {"roi": seed | {"bbox_xyxy": [0, 0, 20, 20]}},
                {},
            )
        )
    frame = polygon([[0, 0], [100, 0], [100, 100], [0, 100]])
    frame.update(roi_kind="bbox", bbox_xyxy=[0, 0, float("inf"), 100])
    with pytest.raises(InvalidRequestError, match="有限"):
        handle_node(request("geometry", "roi_array", {"roi": seed, "frame": frame}, {}))
