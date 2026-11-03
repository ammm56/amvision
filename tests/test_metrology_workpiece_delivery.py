"""工件交付文档独立于测试构图器，原测量定义和所有五十项保持完整。"""

import json
from pathlib import Path

import pytest

from backend.contracts.workflows.metrology import LimitRule, NumericTable
from backend.nodes.core_nodes.support.measurement import check_limits
from scripts.metrology_workpiece import app_document, build_documents
from tests.integration.metrology3d.workpiece_workflow import workpiece_documents

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("input_kind", ["file", "array"])
@pytest.mark.parametrize("view", ["full", "numeric"])
def test_delivery_preserves_measurement_algorithms(input_kind, view):
    """交付只改输入和输出，不改拟面、选点、求交或拟圆门禁。"""
    graph, app = build_documents(input_kind=input_kind, view=view)
    baseline, _ = workpiece_documents(file=input_kind == "file", visible=True)
    nodes = {n.node_id: n for n in graph.nodes}
    for source in baseline.nodes:
        if (
            source.node_type_id.startswith("custom.metrology3d.")
            and source.node_id != "preview"
        ):
            assert nodes[source.node_id].parameters == source.parameters
    assert len(nodes["limits"].parameters["rules"]) == 50
    assert len({r["item_id"] for r in nodes["limits"].parameters["rules"]}) == 50
    assert ("preview" in nodes) is (view == "full")
    assert ("read" in nodes) is (input_kind == "file")
    assert app.template_ref.template_id == graph.template_id
    assert (
        app_document(input_kind=input_kind, view=view)["format_id"]
        == "amvision.workflow-app-document.v1"
    )
    assert len({e.edge_id for e in graph.edges}) == len(graph.edges)
    assert {n for g in graph.groups for n in g.member_node_ids} == set(nodes)
    assert (
        nodes["save-result"].parameters["save_directory"] == "{workflow_app_result_dir}"
    )
    assert {"limits", "inspection", "save-result"} <= nodes.keys()
    if view == "full":
        evidence = {
            e.source_node_id
            for e in graph.edges
            if e.target_node_id == "preview" and e.target_port == "evidence"
        }
        assert len(evidence) == 38


def test_delivery_rules_accept_values_but_reject_missing_and_outside():
    """冻结工程限值有明确 NG/INVALID，不能从样本自动调整到合格。"""
    graph, _ = build_documents()
    rules = tuple(
        LimitRule.model_validate(r)
        for n in graph.nodes
        if n.node_id == "limits"
        for r in n.parameters["rules"]
    )
    matrix = json.loads(
        (ROOT / "docs/development/assets/r5-f4/workpiece-windows.json").read_text(
            "utf-8"
        )
    )["items"]
    items = [dict(item_id=k, unit="mm", **v) for k, v in matrix.items()]
    summary = check_limits(NumericTable(observation_id="delivery", items=items), rules)
    assert summary["state"] == "ok" and summary["required_ok_count"] == 50
    items[0]["value"] = 1000.0
    assert (
        check_limits(NumericTable(observation_id="delivery", items=items), rules)[
            "state"
        ]
        == "ng"
    )
    items.pop()
    summary = check_limits(NumericTable(observation_id="delivery", items=items), rules)
    assert summary["state"] == "invalid" and summary["required_invalid_count"] == 1


def test_public_delivery_has_no_test_or_local_data_dependencies():
    """普通工程师只需要文档、已启用节点包和输入点云。"""
    document = json.dumps(app_document(), ensure_ascii=False)
    assert "tests." not in document and "W:\\" not in document
    assert "model-version-" not in document and "resource_id" not in document


@pytest.mark.parametrize("delta,accepted", [(0, True), (5e-8, True), (2e-7, False)])
def test_delivery_comparison_uses_only_absolute_tolerance(tmp_path, delta, accepted):
    """二十毫米量值不能借默认相对容差放过超过 1e-7 mm 的偏差。"""
    from types import SimpleNamespace
    from tests.integration.metrology3d.workpiece_workflow import check_record

    baseline = json.loads(
        (ROOT / "docs/development/assets/r5-f4/workpiece-windows.json").read_text(
            "utf-8"
        )
    )["items"]
    items = [dict(item_id=key, unit="mm", **value) for key, value in baseline.items()]
    next(item for item in items if item["item_id"] == "S2.D")["value"] += delta
    record = dict(
        format_id="amvision.result-record.v1",
        state="ok",
        passed=True,
        conditions={"items": [None] * 50},
        metrics={"items": items},
    )
    (tmp_path / "result.json").write_text(json.dumps(record), encoding="utf-8")
    body = dict(
        code=0,
        data=record,
        meta={"saved_output": {"kind": "object-store", "object_key": "result.json"}},
    )
    system = SimpleNamespace(
        settings=SimpleNamespace(dataset_storage=SimpleNamespace(root_dir=tmp_path))
    )
    if accepted:
        check_record(body, system)
    else:
        with pytest.raises(AssertionError, match="S2.D"):
            check_record(body, system)
