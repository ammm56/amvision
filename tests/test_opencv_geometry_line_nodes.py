"""通用 line 几何节点测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader


def test_quadrilateral_from_lines_builds_explicit_ordered_roi() -> None:
    """验证 Top/Right/Bottom/Left 四个显式输入可构造稳定四边形。"""

    result = _create_executor().execute(
        template=_quadrilateral_template(),
        input_values={
            "top": _lines_payload((10, 20), (110, 22)),
            "right": _lines_payload((110, 22), (108, 82)),
            "bottom": _lines_payload((12, 80), (108, 82)),
            "left": _lines_payload((10, 20), (12, 80)),
        },
        execution_metadata={"workflow_run_id": "line-quad-success"},
    )

    points = result.outputs["roi"]["polygon_xy"]
    assert points[0] == pytest.approx([10.0, 20.0])
    assert points[1] == pytest.approx([110.0, 22.0])
    assert points[2] == pytest.approx([108.0, 82.0])
    assert points[3] == pytest.approx([12.0, 80.0])


def test_quadrilateral_from_lines_rejects_parallel_boundaries() -> None:
    """验证无交点的平行边线会快速失败，而不是输出无效坐标。"""

    with pytest.raises(InvalidRequestError, match="平行"):
        _create_executor().execute(
            template=_quadrilateral_template(),
            input_values={
                "top": _lines_payload((0, 0), (100, 0)),
                "right": _lines_payload((0, 10), (100, 10)),
                "bottom": _lines_payload((0, 100), (100, 100)),
                "left": _lines_payload((0, 0), (0, 100)),
            },
            execution_metadata={"workflow_run_id": "line-quad-parallel"},
        )


def test_line_deduplicate_preserves_distinct_parallel_lines() -> None:
    """验证重复线段被过滤，物理位置不同的平行线仍保留。"""

    result = _create_executor().execute(
        template=_line_deduplicate_template(),
        input_values={
            "lines": {
                "items": [
                    _line_item((0, 10), (100, 10), 1),
                    _line_item((10, 11), (90, 11), 2),
                    _line_item((0, 40), (100, 40), 3),
                ],
                "count": 3,
            }
        },
        execution_metadata={"workflow_run_id": "line-deduplicate"},
    )

    assert result.outputs["lines"]["count"] == 2
    assert [item["midpoint_xy"][1] for item in result.outputs["lines"]["items"]] == [10.0, 40.0]


def _quadrilateral_template() -> WorkflowGraphTemplate:
    """构造 Quadrilateral From Lines 最小执行图。"""

    node_id = "quad"
    return WorkflowGraphTemplate(
        template_id="opencv-line-quadrilateral",
        template_version="1.0.0",
        display_name="Line Quadrilateral",
        nodes=(
            WorkflowGraphNode(
                node_id=node_id,
                node_type_id="custom.opencv.quadrilateral-from-lines",
                parameters={"min_width": 50, "min_height": 30},
            ),
        ),
        template_inputs=tuple(
            WorkflowGraphInput(
                input_id=port_name,
                display_name=port_name,
                payload_type_id="lines.v1",
                target_node_id=node_id,
                target_port=port_name,
            )
            for port_name in ("top", "right", "bottom", "left")
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                source_node_id=node_id,
                source_port="roi",
            ),
        ),
    )


def _line_deduplicate_template() -> WorkflowGraphTemplate:
    """构造 Line Deduplicate 最小执行图。"""

    node_id = "deduplicate"
    return WorkflowGraphTemplate(
        template_id="opencv-line-deduplicate",
        template_version="1.0.0",
        display_name="Line Deduplicate",
        nodes=(
            WorkflowGraphNode(
                node_id=node_id,
                node_type_id="custom.opencv.line-deduplicate",
                parameters={"angle_tolerance_deg": 2, "distance_tolerance_pixels": 4},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="lines",
                display_name="Lines",
                payload_type_id="lines.v1",
                target_node_id=node_id,
                target_port="lines",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="lines",
                display_name="Lines",
                payload_type_id="lines.v1",
                source_node_id=node_id,
                source_port="lines",
            ),
        ),
    )


def _lines_payload(start_xy: tuple[float, float], end_xy: tuple[float, float]) -> dict[str, object]:
    """构造单线 lines.v1。"""

    return {"items": [_line_item(start_xy, end_xy, 1)], "count": 1}


def _line_item(
    start_xy: tuple[float, float],
    end_xy: tuple[float, float],
    line_index: int,
) -> dict[str, object]:
    """构造规范 line item。"""

    delta_x = end_xy[0] - start_xy[0]
    delta_y = end_xy[1] - start_xy[1]
    return {
        "line_index": line_index,
        "start_xy": list(start_xy),
        "end_xy": list(end_xy),
        "midpoint_xy": [
            (start_xy[0] + end_xy[0]) / 2.0,
            (start_xy[1] + end_xy[1]) / 2.0,
        ],
        "length_pixels": (delta_x * delta_x + delta_y * delta_y) ** 0.5,
        "angle_deg": 0.0,
    }


def _create_executor() -> WorkflowGraphExecutor:
    """创建加载仓库 custom nodes 的执行器。"""

    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=NodeCatalogRegistry(node_pack_loader=node_pack_loader),
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    return WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
