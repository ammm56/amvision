"""通用网格与上游 ROI 阵列的几何等价和交互边界。"""

import pytest

from backend.nodes.core_nodes.vision.roi import roi_grid_create as grid
from backend.nodes.core_nodes.support.roi import build_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes import roi_array
from scripts.validate_linescan_front_registration import request


def grid_request(parameters):
    """不解码图像，仅用标准图像引用核对几何。"""
    return WorkflowNodeExecutionRequest(
        node_id="grid",
        node_definition=object(),
        parameters=parameters,
        input_values={
            "image": {
                "transport_kind": "memory",
                "image_handle": "test",
                "media_type": "image/bgr24",
                "width": 2500,
                "height": 2048,
            }
        },
        execution_metadata={},
    )


def test_polygon_grid_matches_upstream_array_including_cross_axis_steps(monkeypatch):
    """直接网格必须逐点等价于首槽＋父框＋阵列，而非只比较输出数目。"""
    local = [
        [400, 95],
        [510, 95],
        [510, 350],
        [320, 350],
        [320, 450],
        [400, 450],
        [400, 605],
        [75, 605],
        [75, 330],
        [160, 330],
        [160, 160],
        [300, 160],
        [300, 250],
        [400, 250],
    ]
    seed = build_roi_payload(
        roi_id="seed",
        display_name=None,
        roi_kind="polygon",
        polygon_xy=local,
        bbox_xyxy=[75, 95, 510, 605],
        area=1,
    )
    frame = build_roi_payload(
        roi_id="tray",
        display_name=None,
        roi_kind="bbox",
        bbox_xyxy=[30, 60, 2370, 1760],
        polygon_xy=[[30, 60], [2370, 60], [2370, 1760], [30, 1760]],
        area=3978000,
    )
    original = roi_array.handle_node(
        request(
            "geometry",
            "roi_array",
            {"roi": seed, "frame": frame},
            {
                "rows": 3,
                "columns": 6,
                "column_step_xy": [343, -3],
                "row_step_xy": [4, 500],
            },
        )
    )
    captured = {}

    def preview(_request, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(grid, "build_debug_image_preview_output", preview)
    result = grid._roi_grid_create_handler(
        grid_request(
            {
                "rows": 3,
                "columns": 6,
                "roi_kind": "polygon",
                "polygon_xy": [[x + 30, y + 60] for x, y in local],
                "step_x": 343,
                "column_step_y": -3,
                "row_step_x": 4,
                "step_y": 500,
            }
        )
    )
    for before, after in zip(
        original["rois"]["items"], result["rois"]["items"], strict=True
    ):
        assert before["polygon_xy"] == after["polygon_xy"]
        assert before["bbox_xyxy"] == after["bbox_xyxy"]
        assert before["area"] == after["area"]
    tools = captured["interaction"]["tools"]
    assert tools[0]["tool"] == "polygon"
    assert not {"roi_width", "roi_height"} & {
        c["parameter_name"] for c in captured["interaction"]["controls"]
    }
    assert all(overlay["pickable"] is False for overlay in captured["overlays"][1:])
    lines = [t for t in tools if t["tool"] == "line"]
    assert [t["target_parameters"] for t in lines] == [
        ["step_x", "column_step_y"],
        ["row_step_x", "step_y"],
    ]
    assert captured["overlays"][0]["target_parameters"] == ["polygon_xy"]
    assert all(
        not overlay.get("target_parameters") for overlay in captured["overlays"][1:]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"bounds_policy": "clip"},
        {"polygon_xy": [[0, 0], [1, 1], [2, 2]]},
        {"step_x": 0, "column_step_y": 0},
        {"step_x": 1, "column_step_y": 2, "row_step_x": 2, "step_y": 4},
        {"polygon_xy": [[-1, 0], [2, 0], [2, 2]]},
    ],
)
def test_polygon_grid_rejects_ambiguous_geometry(changes):
    """禁止退化向量、越界和只裁框不裁多边形的隐式几何变化。"""
    with pytest.raises(InvalidRequestError):
        grid._roi_grid_create_handler(
            grid_request(
                {
                    "roi_kind": "polygon",
                    "polygon_xy": [[10, 10], [20, 10], [20, 20]],
                    "rows": 2,
                    "columns": 2,
                    "step_x": 30,
                    "step_y": 30,
                    **changes,
                }
            )
        )


def test_upstream_roi_array_exposes_two_independent_step_tools(monkeypatch):
    """上游首槽只读，交互明确写回本节点的行、列步距。"""
    captured = {}

    def preview(_request, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(roi_array, "build_debug_image_preview_output", preview)
    seed = build_roi_payload(
        roi_id="seed",
        display_name=None,
        roi_kind="bbox",
        bbox_xyxy=[10, 10, 20, 20],
        polygon_xy=[[10, 10], [20, 10], [20, 20], [10, 20]],
        area=100,
    )
    roi_array.handle_node(
        request(
            "geometry",
            "roi_array",
            {"roi": seed, "image": grid_request({}).input_values["image"]},
            {
                "rows": 2,
                "columns": 2,
                "column_step_xy": [30, -2],
                "row_step_xy": [1, 30],
            },
        )
    )
    tools = captured["interaction"]["tools"]
    assert [tool["target_parameters"] for tool in tools] == [
        ["column_step_xy"],
        ["row_step_xy"],
    ]
    for tool, vector in zip(tools, [[30, -2], [1, 30]], strict=True):
        a, b = tool["initial_points_xy"]
        assert [b[0] - a[0], b[1] - a[1]] == vector
