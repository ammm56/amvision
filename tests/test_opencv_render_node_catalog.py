"""OpenCV 渲染节点目录测试。"""

from __future__ import annotations

import json

from backend.service.api.rest.v1.routes.workflows.node_catalog_helpers import (
    _with_effective_parameter_ui_schema,
)
from custom_nodes.opencv_nodes.categories.render.workflow.catalog_builder import (
    build_custom_node_catalog_document,
    build_custom_node_catalog_payload,
    get_workflow_dir,
)


def test_opencv_render_node_catalog_builder_matches_checked_in_catalog() -> None:
    """验证渲染节点目录碎片与生成文件完全一致。"""

    workflow_dir = get_workflow_dir()
    expected = json.loads(
        (workflow_dir / "catalog.json").read_text(encoding="utf-8")
    )

    assert build_custom_node_catalog_payload() == expected


def test_draw_regions_declares_generic_color_map_widget() -> None:
    """验证 Draw Regions 通过通用 UI 元数据声明颜色映射编辑器。"""

    payload = build_custom_node_catalog_payload()
    draw_regions = next(
        item
        for item in payload["node_definitions"]
        if item["node_type_id"] == "custom.opencv.draw-regions"
    )
    class_colors = draw_regions["parameter_schema"]["properties"]["class_colors"]

    assert class_colors["x-amvision-ui"]["widget"] == "color-map"
    assert class_colors["propertyNames"]["title"] == "Class Name"
    assert class_colors["additionalProperties"]["format"] == "color"


def test_draw_regions_exposes_color_map_in_effective_ui_schema() -> None:
    """验证 Catalog 编译后把受控 widget 传给前端且移除源扩展。"""

    catalog = build_custom_node_catalog_document()
    definition = next(
        item
        for item in catalog.node_definitions
        if item.node_type_id == "custom.opencv.draw-regions"
    )
    effective_definition = _with_effective_parameter_ui_schema(definition)
    class_colors = next(
        item
        for item in effective_definition.parameter_ui_schema.fields
        if item.parameter_name == "class_colors"
    )

    assert class_colors.widget == "color-map"
    assert "x-amvision-ui" not in class_colors.json_schema
    assert class_colors.json_schema["additionalProperties"]["format"] == "color"
