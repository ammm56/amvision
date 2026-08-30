"""工业二维视觉 Workflow Template/Application 示例契约测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
    validate_flow_application_bindings,
    validate_workflow_graph_template,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry


EXAMPLE_EXPECTATIONS = {
    "industrial_vision_grayscale_locate": {"custom.opencv.template-match"},
    "industrial_vision_feature_locate": {"custom.opencv.feature-locate"},
    "industrial_vision_shape_locate": {"custom.opencv.shape-locate"},
    "industrial_vision_subpixel_edge_measure": {"custom.opencv.edge-pair-measure"},
    "industrial_vision_stereo_calibration_diagnose": {
        "custom.opencv.stereo-calibrate",
        "custom.opencv.stereo-rectify",
    },
    "industrial_vision_bead_inspect": {"custom.opencv.bead-inspect"},
    "industrial_vision_contour_deviation": {
        "custom.opencv.contour-deviation-inspect"
    },
}


def _registry(repository_root: Path) -> NodeCatalogRegistry:
    """构建包含当前仓库全部 Node Pack 的目录。"""

    loader = LocalNodePackLoader(repository_root / "custom_nodes")
    loader.refresh()
    return NodeCatalogRegistry(node_pack_loader=loader)


@pytest.mark.parametrize("example_name", sorted(EXAMPLE_EXPECTATIONS))
def test_industrial_vision_workflow_examples_are_current_and_valid(
    example_name: str,
) -> None:
    """验证七组示例可被当前图、绑定和 Node Catalog 契约解析。"""

    repository_root = Path(__file__).resolve().parents[1]
    example_dir = repository_root / "docs" / "examples" / "workflows"
    template = WorkflowGraphTemplate.model_validate(
        json.loads(
            (example_dir / f"{example_name}.template.json").read_text(encoding="utf-8")
        )
    )
    application = FlowApplication.model_validate(
        json.loads(
            (example_dir / f"{example_name}.application.json").read_text(
                encoding="utf-8"
            )
        )
    )
    registry = _registry(repository_root)
    validate_workflow_graph_template(
        template=template,
        node_definitions=registry.get_workflow_node_definitions(),
    )
    validate_flow_application_bindings(template=template, application=application)

    node_type_ids = {node.node_type_id for node in template.nodes}
    assert EXAMPLE_EXPECTATIONS[example_name] <= node_type_ids
    assert not any("python" in node_type_id for node_type_id in node_type_ids)
    assert application.template_ref.template_id == template.template_id
    assert application.template_ref.template_version == template.template_version
    assert application.template_ref.source_uri == (
        f"docs/examples/workflows/{example_name}.template.json"
    )
    assert application.metadata["example_kind"] == template.metadata["example_kind"]
