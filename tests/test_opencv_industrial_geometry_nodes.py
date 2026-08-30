"""工业二维几何创建、选择、变换和关系节点测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.industrial_geometry import (
    NODE_HANDLERS,
    handle_circle_circle_relation,
    handle_circle_create,
    handle_circles_select,
    handle_ellipse_create,
    handle_ellipses_select,
    handle_line_circle_relation,
    handle_line_create,
    handle_line_line_relation,
    handle_lines_select,
    handle_pixel_to_world,
    handle_point_circle_relation,
    handle_point_create,
    handle_points_select,
    handle_transform_compose,
    handle_transform_create,
    handle_transform_invert,
    handle_transform_points,
    handle_world_to_pixel,
)
from custom_nodes.opencv_nodes.categories.geometry.workflow.catalog_builder import (
    build_custom_node_catalog_payload,
)
from custom_nodes.opencv_nodes.shared.workflow.payload_contracts import (
    load_shared_opencv_payload_contracts_payload,
)


INDUSTRIAL_GEOMETRY_NODE_IDS = {
    "custom.opencv.point-create",
    "custom.opencv.line-create",
    "custom.opencv.circle-create",
    "custom.opencv.ellipse-create",
    "custom.opencv.points-select",
    "custom.opencv.lines-select",
    "custom.opencv.circles-select",
    "custom.opencv.ellipses-select",
    "custom.opencv.transform-2d-create",
    "custom.opencv.transform-2d-compose",
    "custom.opencv.transform-2d-invert",
    "custom.opencv.transform-points",
    "custom.opencv.pixel-to-world",
    "custom.opencv.world-to-pixel",
    "custom.opencv.line-line-relation",
    "custom.opencv.point-circle-relation",
    "custom.opencv.line-circle-relation",
    "custom.opencv.circle-circle-relation",
}


def _request(
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造轻量 OpenCV 节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="geometry-test",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
    )


def _point_payload(items: list[list[float]], *, coordinate_space: str = "image-pixels") -> dict[str, object]:
    """创建测试 points.v1。"""

    return handle_point_create(
        _request(
            parameters={
                "points": items,
                "coordinate_space": coordinate_space,
                "unit": "pixel",
            }
        )
    )["points"]


def _line_payload(
    start_xy: list[float],
    end_xy: list[float],
    *,
    coordinate_space: str = "image-pixels",
) -> dict[str, object]:
    """创建测试 lines.v1。"""

    return handle_line_create(
        _request(
            parameters={
                "start_xy": start_xy,
                "end_xy": end_xy,
                "coordinate_space": coordinate_space,
                "unit": "pixel",
            }
        )
    )["lines"]


def _circle_payload(
    center_xy: list[float],
    radius: float,
    *,
    coordinate_space: str = "image-pixels",
) -> dict[str, object]:
    """创建测试 circles.v1。"""

    return handle_circle_create(
        _request(
            parameters={
                "center_xy": center_xy,
                "radius": radius,
                "coordinate_space": coordinate_space,
                "unit": "pixel",
            }
        )
    )["circles"]


def test_geometry_catalog_and_handlers_are_in_parity() -> None:
    """验证 18 个源定义与运行时 handler 一一对应。"""

    repository_root = Path(__file__).resolve().parents[1]
    workflow_dir = (
        repository_root
        / "custom_nodes"
        / "opencv_nodes"
        / "categories"
        / "geometry"
        / "workflow"
    )
    catalog = build_custom_node_catalog_payload(workflow_dir=workflow_dir)
    catalog_ids = {item["node_type_id"] for item in catalog["node_definitions"]}
    handler_ids = {node_type_id for node_type_id, _handler in NODE_HANDLERS}

    assert INDUSTRIAL_GEOMETRY_NODE_IDS <= catalog_ids
    assert INDUSTRIAL_GEOMETRY_NODE_IDS == handler_ids


def test_geometry_create_and_select_preserve_context_and_reindex() -> None:
    """验证四类几何创建/选择保持 coordinate space 和 unit。"""

    points = _point_payload([[0, 0], [2, 3], [5, 8]])
    selected_points = handle_points_select(
        _request(parameters={"indexes": [3, 1]}, input_values={"points": points})
    )["points"]
    assert [item["xy"] for item in selected_points["items"]] == [[5.0, 8.0], [0.0, 0.0]]
    assert [item["point_index"] for item in selected_points["items"]] == [0, 1]

    lines = _line_payload([0, 0], [3, 4])
    assert lines["items"][0]["length_pixels"] == pytest.approx(5.0)
    assert handle_lines_select(
        _request(parameters={"filter_field": "length_pixels", "minimum": 5}, input_values={"lines": lines})
    )["lines"]["count"] == 1

    circles = _circle_payload([10, 10], 4)
    assert handle_circles_select(
        _request(parameters={"indexes": [1]}, input_values={"circles": circles})
    )["circles"]["items"][0]["diameter"] == pytest.approx(8.0)

    ellipses = handle_ellipse_create(
        _request(
            parameters={
                "center_xy": [20, 10],
                "major_axis": 12,
                "minor_axis": 6,
                "angle_deg": 30,
                "coordinate_space": "image-pixels",
                "unit": "pixel",
            }
        )
    )["ellipses"]
    assert handle_ellipses_select(
        _request(parameters={"indexes": [1]}, input_values={"ellipses": ellipses})
    )["ellipses"]["count"] == 1


def test_transform_create_compose_invert_and_apply_have_explicit_direction() -> None:
    """验证执行顺序为先 A 后 B，即 composed=B@A，且反演可往返。"""

    translation = handle_transform_create(
        _request(
            parameters={
                "transform_kind": "rigid",
                "source_coordinate_space": "source",
                "target_coordinate_space": "translated",
                "translation_x": 10,
                "translation_y": 5,
            }
        )
    )["transform"]
    scale = handle_transform_create(
        _request(
            parameters={
                "transform_kind": "similarity",
                "source_coordinate_space": "translated",
                "target_coordinate_space": "target",
                "scale": 2,
            }
        )
    )["transform"]
    composed = handle_transform_compose(
        _request(input_values={"transforms": (translation, scale)})
    )["transform"]
    points = _point_payload([[1, 2]], coordinate_space="source")
    transformed = handle_transform_points(
        _request(input_values={"points": points, "transform": composed})
    )["points"]
    assert transformed["coordinate_space"] == "target"
    assert transformed["items"][0]["xy"] == pytest.approx([22.0, 14.0])

    inverse = handle_transform_invert(
        _request(input_values={"transform": composed})
    )["transform"]
    restored = handle_transform_points(
        _request(input_values={"points": transformed, "transform": inverse})
    )["points"]
    assert restored["items"][0]["xy"] == pytest.approx([1.0, 2.0])


def test_pixel_world_conversion_requires_explicit_plane_transform() -> None:
    """验证像素/世界换算使用明确平面 transform 和单位。"""

    pixel_to_world = handle_transform_create(
        _request(
            parameters={
                "transform_kind": "similarity",
                "source_coordinate_space": "camera-pixels",
                "target_coordinate_space": "fixture-mm",
                "scale": 0.1,
            }
        )
    )["transform"]
    pixel_points = _point_payload([[100, 50]], coordinate_space="camera-pixels")
    world_points = handle_pixel_to_world(
        _request(
            parameters={"world_unit": "millimeter"},
            input_values={"points": pixel_points, "transform": pixel_to_world},
        )
    )["points"]
    assert world_points["unit"] == "millimeter"
    assert world_points["items"][0]["xy"] == pytest.approx([10.0, 5.0])
    inverse = handle_transform_invert(
        _request(input_values={"transform": pixel_to_world})
    )["transform"]
    restored = handle_world_to_pixel(
        _request(input_values={"points": world_points, "transform": inverse})
    )["points"]
    assert restored["unit"] == "pixel"
    assert restored["items"][0]["xy"] == pytest.approx([100.0, 50.0])


def test_transform_rejects_singular_matrix_and_coordinate_mismatch() -> None:
    """验证奇异矩阵和错误方向不会静默执行。"""

    with pytest.raises(InvalidRequestError, match="奇异"):
        handle_transform_create(
            _request(
                parameters={
                    "transform_kind": "homography",
                    "source_coordinate_space": "a",
                    "target_coordinate_space": "b",
                    "matrix_3x3": [[1, 0, 0], [0, 0, 0], [0, 0, 1]],
                }
            )
        )
    transform = handle_transform_create(
        _request(
            parameters={
                "transform_kind": "rigid",
                "source_coordinate_space": "a",
                "target_coordinate_space": "b",
            }
        )
    )["transform"]
    with pytest.raises(InvalidRequestError, match="source 不一致"):
        handle_transform_points(
            _request(
                input_values={
                    "points": _point_payload([[0, 0]], coordinate_space="wrong"),
                    "transform": transform,
                }
            )
        )


def test_geometry_relations_cover_intersection_tangent_and_separation() -> None:
    """验证点线圆关系输出结构化状态、距离与交点。"""

    horizontal = _line_payload([-10, 0], [10, 0])
    vertical = _line_payload([0, -10], [0, 10])
    line_line = handle_line_line_relation(
        _request(input_values={"first_lines": horizontal, "second_lines": vertical})
    )
    assert line_line["summary"]["value"]["relation"] == "intersecting"
    assert line_line["summary"]["value"]["intersection_points"][0] == pytest.approx([0, 0])

    circle = _circle_payload([0, 0], 5)
    point_circle = handle_point_circle_relation(
        _request(input_values={"points": _point_payload([[8, 0]]), "circles": circle})
    )
    assert point_circle["summary"]["value"]["signed_distance"] == pytest.approx(3.0)

    tangent_line = _line_payload([-10, 5], [10, 5])
    line_circle = handle_line_circle_relation(
        _request(input_values={"lines": tangent_line, "circles": circle})
    )
    assert line_circle["summary"]["value"]["relation"] == "tangent"
    assert len(line_circle["summary"]["value"]["intersection_points"]) == 1

    second_circle = _circle_payload([12, 0], 5)
    circle_circle = handle_circle_circle_relation(
        _request(input_values={"first_circles": circle, "second_circles": second_circle})
    )
    assert circle_circle["summary"]["value"]["relation"] == "separate"
    assert circle_circle["summary"]["value"]["external_clearance"] == pytest.approx(2.0)

    schemas = {
        item["payload_type_id"]: item["json_schema"]
        for item in load_shared_opencv_payload_contracts_payload()
    }
    Draft202012Validator(schemas["measurements.v1"]).validate(
        circle_circle["measurements"]
    )


def test_geometry_relation_rejects_coordinate_space_mismatch() -> None:
    """验证跨坐标空间关系计算快速失败。"""

    with pytest.raises(InvalidRequestError, match="coordinate_space"):
        handle_line_circle_relation(
            _request(
                input_values={
                    "lines": _line_payload([0, 0], [1, 0], coordinate_space="a"),
                    "circles": _circle_payload([0, 0], 1, coordinate_space="b"),
                }
            )
        )
