"""代表配方页面文档沿现有格式生成，检查接线与显式显示容量。"""

import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)
from backend.service.application.workflows.point_cloud.execution_policy import (
    PointCloudExecutionPolicy,
)
from tests.integration.metrology3d.export_representative_document import main
from tests.integration.metrology3d.representative_workflow import (
    representative_documents,
)


def test_export_representative_document(tmp_path, monkeypatch):
    """分开总览和逐点拟面分类；测量参数及测量分支接线不能被显示配置改写。"""
    output, policy_path = tmp_path / "recipe.json", tmp_path / "policy.json"
    monkeypatch.setattr(
        "sys.argv", ["export", str(output), "--policy-output", str(policy_path)]
    )
    main()
    document = json.loads(output.read_text("utf-8"))
    assert document["format_id"] == "amvision.workflow-app-document.v1"
    graph = WorkflowGraphTemplate.model_validate(document["template"])
    FlowApplication.model_validate(document["application"])
    policy = PointCloudExecutionPolicy.model_validate_json(
        policy_path.read_text("utf-8")
    )
    baseline, _ = representative_documents(file=True)
    nodes = {node.node_id: node for node in graph.nodes}
    assert len(nodes) == 22
    assert graph.template_outputs[0].source_node_id == "response"
    assert {e.source_node_id for e in graph.edges if e.target_node_id == "results"} == {
        "H",
        "Z",
        "extents",
        "diameter",
    }
    for node in baseline.nodes:
        if node.node_id != "preview":
            assert nodes[node.node_id].parameters == node.parameters
    overview, planes = nodes["preview"], nodes["plane-preview"]
    assert overview.parameters["point_limit"] == 500000
    assert planes.parameters["point_limit"] == 1000
    assert {
        e.source_node_id for e in graph.edges if e.target_node_id == "plane-preview"
    } == {"filter", "D", "B", "T"}
    assert not any(
        e.target_node_id == "preview" and e.source_node_id in {"D", "B", "T"}
        for e in graph.edges
    )
    assert policy.preview.max_working_bytes == 128 * 1024**2
    assert policy.renderer.max_points >= 510000
    assert policy.renderer.max_data_bytes >= 510000 * 20
    assert policy.renderer.max_cpu_bytes == 128 * 1024**2


def test_manual_document_preserves_parameters_and_wiring(tmp_path, monkeypatch):
    """空白页面逐节点配置的导出物必须与已验算法参数和接线一致。"""
    output = tmp_path / "reference.json"
    monkeypatch.setattr("sys.argv", ["export", str(output)])
    main()
    baseline = json.loads(output.read_text("utf-8"))["template"]
    path = Path(__file__).resolve().parents[3] / (
        "docs/development/assets/r5-e/manual-workflow.json"
    )
    manual = json.loads(path.read_text("utf-8"))
    graph = WorkflowGraphTemplate.model_validate(manual["template"])
    app = FlowApplication.model_validate(manual["application"])
    aliases = {
        "read": "custom_metrology3d_read_cloud",
        "filter": "custom_metrology3d_filter_valid",
        "D-crop": "custom_metrology3d_crop_roi",
        "D": "custom_metrology3d_fit_plane",
        "B-crop": "custom_metrology3d_crop_roi_2",
        "B": "custom_metrology3d_fit_plane_2",
        "T-crop": "custom_metrology3d_crop_roi_3",
        "T": "custom_metrology3d_fit_plane_3",
        "frame": "custom_metrology3d_build_frame",
        "H": "custom_metrology3d_measure_step",
        "Z": "custom_metrology3d_measure_step_2",
        "A_top_L": "custom_metrology3d_extract_boundary",
        "S1": "custom_metrology3d_extract_boundary_2",
        "circle": "custom_metrology3d_fit_circle",
        "diameter": "custom_metrology3d_measure_hole",
        "extents": "custom_metrology3d_measure_extents",
        "results": "core_value_numeric_tables_merge",
        "values": "core_value_numeric_table_to_value",
        "response": "core_output_response_envelope",
        "table": "core_io_value_preview",
        "preview": "custom_metrology3d_cloud_preview",
        "plane-preview": "custom_metrology3d_cloud_preview_2",
    }

    def canonical(value):
        """ROI 定义是按 ID 引用的集合；只规范其顺序，不忽略任何字段。"""
        if isinstance(value, dict):
            return {
                key: canonical(sorted(item, key=lambda roi: roi["roi_id"]))
                if key == "rois"
                else canonical(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [canonical(item) for item in value]
        return value

    nodes = {node.node_id: node for node in graph.nodes}
    assert len(nodes) == 23
    for node in baseline["nodes"]:
        actual = nodes[aliases[node["node_id"]]]
        assert actual.node_type_id == node["node_type_id"]
        assert canonical(actual.parameters) == canonical(node["parameters"])
    expected = {
        (
            aliases[e["source_node_id"]],
            e["source_port"],
            aliases[e["target_node_id"]],
            e["target_port"],
        )
        for e in baseline["edges"]
    }
    expected.add(("core_io_template_input_file", "file", aliases["read"], "file"))
    actual = {
        (e.source_node_id, e.source_port, e.target_node_id, e.target_port)
        for e in graph.edges
    }
    assert actual == expected and len(graph.edges) == len(expected)
    assert len(graph.template_inputs) == len(graph.template_outputs) == 1
    assert graph.template_inputs[0].target_node_id == "core_io_template_input_file"
    assert graph.template_outputs[0].source_node_id == aliases["response"]
    assert graph.template_outputs[0].source_port == "body"
    assert {binding.direction for binding in app.bindings} == {"input", "output"}
