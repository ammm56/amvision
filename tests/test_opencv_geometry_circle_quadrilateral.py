"""Quadrilateral From Circle Centers 节点测试。"""

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
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)


def test_quadrilateral_from_circle_centers_builds_ordered_roi() -> None:
    """验证四个显式角点 circle 可构成稳定有序的 polygon ROI。"""

    result = _create_executor().execute(
        template=_build_template(),
        input_values={
            "top_left": _build_circles_payload(10, 20),
            "top_right": _build_circles_payload(110, 22),
            "bottom_right": _build_circles_payload(108, 82),
            "bottom_left": _build_circles_payload(12, 80),
        },
        execution_metadata={"workflow_run_id": "circle-quad-success"},
    )

    roi = result.outputs["roi"]
    summary = result.outputs["summary"]["value"]
    assert roi["polygon_xy"] == [[10.0, 20.0], [110.0, 22.0], [108.0, 82.0], [12.0, 80.0]]
    assert roi["bbox_xyxy"] == [10.0, 20.0, 110.0, 82.0]
    assert summary["width"] > 99
    assert summary["height"] > 59


def test_quadrilateral_from_circle_centers_rejects_swapped_corners() -> None:
    """验证节点拒绝左右语义接反，避免静默输出自交四边形。"""

    with pytest.raises(InvalidRequestError, match="左右角点顺序无效"):
        _create_executor().execute(
            template=_build_template(),
            input_values={
                "top_left": _build_circles_payload(110, 20),
                "top_right": _build_circles_payload(10, 22),
                "bottom_right": _build_circles_payload(108, 82),
                "bottom_left": _build_circles_payload(12, 80),
            },
            execution_metadata={"workflow_run_id": "circle-quad-invalid"},
        )


def test_quadrilateral_from_circle_centers_applies_local_axis_outsets() -> None:
    """验证 circle center 四边形可沿局部轴显式扩展为真实工件边界。"""

    template = _build_template(
        parameters={
            "min_width": 50,
            "min_height": 30,
            "left_outset": 5,
            "right_outset": 7,
            "top_outset": 3,
            "bottom_outset": 4,
        }
    )
    result = _create_executor().execute(
        template=template,
        input_values={
            "top_left": _build_circles_payload(10, 20),
            "top_right": _build_circles_payload(110, 20),
            "bottom_right": _build_circles_payload(110, 80),
            "bottom_left": _build_circles_payload(10, 80),
        },
        execution_metadata={"workflow_run_id": "circle-quad-outsets"},
    )

    assert result.outputs["roi"]["polygon_xy"] == [
        [5.0, 17.0],
        [117.0, 17.0],
        [117.0, 84.0],
        [5.0, 84.0],
    ]


def _build_template(*, parameters: dict[str, object] | None = None) -> WorkflowGraphTemplate:
    """构造四个 circles 输入和一个 quadrilateral 节点的最小图。"""

    node_id = "quad"
    return WorkflowGraphTemplate(
        template_id="opencv-circle-quadrilateral",
        template_version="1.0.0",
        display_name="Circle Quadrilateral",
        nodes=(
            WorkflowGraphNode(
                node_id=node_id,
                node_type_id="custom.opencv.quadrilateral-from-circle-centers",
                parameters=parameters or {"min_width": 50, "min_height": 30},
            ),
        ),
        template_inputs=tuple(
            WorkflowGraphInput(
                input_id=port_name,
                display_name=port_name,
                payload_type_id="circles.v1",
                target_node_id=node_id,
                target_port=port_name,
            )
            for port_name in ("top_left", "top_right", "bottom_right", "bottom_left")
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="roi",
                display_name="ROI",
                payload_type_id="roi.v1",
                source_node_id=node_id,
                source_port="roi",
            ),
            WorkflowGraphOutput(
                output_id="summary",
                display_name="Summary",
                payload_type_id="value.v1",
                source_node_id=node_id,
                source_port="summary",
            ),
        ),
    )


def _build_circles_payload(center_x: float, center_y: float) -> dict[str, object]:
    """构造单 circle payload。"""

    radius = 8.0
    return {
        "items": [
            {
                "circle_index": 1,
                "center_xy": [center_x, center_y],
                "radius": radius,
                "diameter": radius * 2,
                "area": 201.0619,
                "bbox_xyxy": [
                    center_x - radius,
                    center_y - radius,
                    center_x + radius,
                    center_y + radius,
                ],
            }
        ],
        "count": 1,
    }


def _create_executor() -> WorkflowGraphExecutor:
    """创建绑定仓库 custom_nodes 的执行器。"""

    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=NodeCatalogRegistry(node_pack_loader=node_pack_loader),
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    return WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
