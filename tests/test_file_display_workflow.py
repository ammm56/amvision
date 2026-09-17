"""经过既有图执行器验证通用计数到磁盘再到显示的全节点链路。"""

import pytest

from tests.test_workflow_runtime_sanitization import _build_runtime_service
from tests.workflow_editor_graph_support import execute_editor_graph
from tests.workflow_file_display_support import build_file_display_graph


def test_editor_preview_does_not_write_without_explicit_opt_in(tmp_path):
    """真实预览执行器的标志不能由调用方 metadata 关闭。"""
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate

    service, _, _ = _build_runtime_service(tmp_path)
    app, graph = build_file_display_graph(tmp_path / "records")
    document = graph.model_dump(mode="json")
    keep = {
        "counts",
        "record",
        "count_ok",
        "count_ng",
        "field_ok",
        "field_ng",
        "append",
    }
    document["nodes"] = [n for n in document["nodes"] if n["node_id"] in keep]
    document["edges"] = [
        e
        for e in document["edges"]
        if e["source_node_id"] in keep and e["target_node_id"] in keep
    ]
    next(n for n in document["nodes"] if n["node_id"] == "append")["parameters"][
        "preview_write"
    ] = False
    document["template_outputs"][0].update(
        source_node_id="append", source_port="receipt"
    )
    app = app.model_copy(update={"metadata": {}})
    result = execute_editor_graph(
        service,
        project_id="project-1",
        application=app,
        template=WorkflowGraphTemplate.model_validate(document),
        input_bindings={"items": {"value": []}},
        execution_metadata={"_preview_execution": False},
    )
    assert result.state == "succeeded", result.error_message
    assert result.outputs["result"]["value"] == {"write_state": "skipped", "reason": "preview_write_disabled"}
    assert not (tmp_path / "records").exists()
    service.session_factory.engine.dispose()


def test_overlay_and_static_rules_are_validated_before_execution(tmp_path):
    """配置绑定拒绝非显示节点，规则错误在保存/发布校验阶段可见。"""
    from backend.contracts.workflows.workflow_app_mode import (
        validate_workflow_app_mode_config,
    )
    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        WorkflowGraphTemplate,
    )
    from backend.service.application.errors import InvalidRequestError

    service, documents, catalog = _build_runtime_service(tmp_path)
    app, graph = build_file_display_graph(
        tmp_path / "records", image_path=tmp_path / "image.jpg"
    )
    assert validate_workflow_app_mode_config(
        application=app,
        template=graph,
        node_definitions=catalog.get_workflow_node_definitions(),
    )
    bad_app = app.model_dump(mode="json")
    bad_app["metadata"]["app_mode"]["displays"][0]["overlay"]["node_id"] = "counts"
    with pytest.raises(ValueError, match="Value Display"):
        validate_workflow_app_mode_config(
            application=FlowApplication.model_validate(bad_app),
            template=graph,
            node_definitions=catalog.get_workflow_node_definitions(),
        )
    bad_graph = graph.model_dump(mode="json")
    next(n for n in bad_graph["nodes"] if n["node_id"] == "counts")["parameters"][
        "rules"
    ][0]["condition"] = {"operator": "invalid"}
    with pytest.raises(InvalidRequestError):
        documents.validate_template(WorkflowGraphTemplate.model_validate(bad_graph))
    service.session_factory.engine.dispose()


@pytest.mark.parametrize("total", [24, 80])
def test_same_input_new_execution_counts_again(tmp_path, total):
    """两次独立正常执行分别累加常量，显式 NG 分组保持独立。"""
    service, _, _ = _build_runtime_service(tmp_path)
    app, graph = build_file_display_graph(tmp_path / "records", total=total)
    items = (
        [{"label": "acceptable-a"}] * (total - 4)
        + [{"label": "defect-b"}] * 2
        + [{"label": "unmapped"}] * 2
    )
    for cycle in (1, 2):
        result = execute_editor_graph(
            service,
            project_id="project-1",
            application=app,
            template=graph,
            input_bindings={"items": {"value": items}},
        )
        assert result.state == "succeeded", result.error_message
        snapshot = result.outputs["result"]["value"]
        assert snapshot["totals"] == dict(
            material_total=total * cycle,
            material_ok=(total - 4) * cycle,
            material_ng=2 * cycle,
            tray_total=cycle,
        )
        body = next(
            r["outputs"]["body"]
            for r in result.node_records
            if r["node_id"] == "values"
        )
        assert body["type"] == "value-display"
        assert body["context"] == snapshot["source"]
        assert body["fields"][-1]["value"] == pytest.approx((total - 4) / total)
