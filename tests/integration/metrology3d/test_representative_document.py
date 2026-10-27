"""代表配方页面文档沿现有格式生成，检查接线与显式显示容量。"""

import json

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
    assert len(nodes) == 18
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
