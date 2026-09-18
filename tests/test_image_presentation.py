"""显式图片与字段连接的正文、来源与执行依赖回归。"""

from copy import deepcopy

import pytest

from backend.nodes.core_nodes.io.image import image_preview
from backend.nodes.core_nodes.support.display_body import validate_display_body
from backend.service.application.errors import InvalidRequestError
from tests.test_file_display_nodes import request


def body():
    """构造不依赖 JSONL 的通用字段显示。"""
    return {"type": "value-display", "fields": [{"label": "Count", "value": 24, "format": "integer"}]}


def test_explicit_presentation_and_plain_image(monkeypatch):
    """无连接是纯图片；同一正文可用于多图且不会改变上游或再次编码。"""
    images = []
    def image(*args, **kwargs):
        images.append(kwargs)
        return {"transport": "test"}
    monkeypatch.setattr(image_preview, "build_preview_response_image_payload", image)
    original = body()
    plain = image_preview.CORE_NODE_SPEC.handler(request(image_preview.CORE_NODE_SPEC))
    assert "presentation" not in plain["body"]
    for _ in range(2):
        result = image_preview.CORE_NODE_SPEC.handler(request(image_preview.CORE_NODE_SPEC, inputs={"presentation": original}))
        assert result["body"]["presentation"] is original
    assert original == body()
    assert len(images) == 3


@pytest.mark.parametrize("bad", [None, {}, {"type": "image-preview"},
    {**body(), "image": {}}, {"type": "value-display", "fields": []},
    {"type": "value-display", "fields": [{"label": "Bad", "value": {"image": "x"}}]},
    {"type": "value-display", "fields": [{"label": "Bad", "value": float("nan")}]},
    {**body(), "context": "x" * (128 * 1024)},
])
def test_presentation_rejects_invalid_or_unbounded_body(bad):
    """不能把其他响应正文、嵌套图片或非有限值作为显示内容。"""
    with pytest.raises(InvalidRequestError):
        validate_display_body(bad)


def test_context_is_optional_but_explicit_constraint_is_checked_before_image(monkeypatch):
    """提供来源约束后，冲突必须在图片编码/保存前失败。"""
    monkeypatch.setattr(image_preview, "build_preview_response_image_payload", lambda *a, **kw: {})
    ctx = {"generation": "file-a", "sequence": 1, "snapshot_revision": "first"}
    payload = {**body(), "context": ctx}
    req = request(image_preview.CORE_NODE_SPEC, inputs={"presentation": payload, "presentation_context": {"value": ctx}})
    assert image_preview.CORE_NODE_SPEC.handler(req)["body"]["presentation"] == payload
    invalid = deepcopy(req.input_values)
    invalid["presentation"]["context"] = {**ctx, "sequence": 2}
    monkeypatch.setattr(image_preview, "build_preview_response_image_payload", lambda *a, **kw: pytest.fail("不应先处理图片"))
    with pytest.raises(InvalidRequestError, match="来源不一致"):
        image_preview.CORE_NODE_SPEC.handler(request(image_preview.CORE_NODE_SPEC, inputs=invalid))


def test_migration_is_explicit_idempotent_and_preserves_source(tmp_path):
    """迁移一次建立真实边，不能改变原文档或覆盖已有不同来源。"""
    from backend.maintenance.workflow_presentation_migration import migrate_presentation_connections
    from tests.workflow_file_display_support import build_file_display_graph
    app, graph = build_file_display_graph(tmp_path, image_path=tmp_path / "image.jpg")
    original = {"application": app.model_dump(mode="json"), "template": graph.model_dump(mode="json")}
    original["template"]["edges"] = [e for e in original["template"]["edges"] if e["target_port"] != "presentation"]
    original["application"]["metadata"]["app_mode"]["displays"][0]["overlay"] = {"node_id": "values", "output_port": "body", "position": "top-left"}
    before = deepcopy(original)
    result = migrate_presentation_connections(original)
    assert original == before
    assert migrate_presentation_connections(result) == result
    assert len(result["template"]["edges"]) == len(original["template"]["edges"]) + 1
    assert "overlay" not in result["application"]["metadata"]["app_mode"]["displays"][0]
    conflict = deepcopy(original)
    conflict["template"]["edges"].append({**result["template"]["edges"][-1], "source_node_id": "other"})
    with pytest.raises(ValueError, match="已有不同来源"):
        migrate_presentation_connections(conflict)


def test_image_scope_includes_display_ancestors_and_rejects_disabled_source(tmp_path):
    """图片节点级运行沿真实依赖取统计正文；禁用来源不能变为纯图。"""
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate, validate_workflow_graph_template
    from backend.service.application.workflows.execution.topology import build_ancestor_node_ids
    from tests.test_workflow_runtime_sanitization import _build_runtime_service
    from tests.workflow_file_display_support import build_file_display_graph
    service, _, catalog = _build_runtime_service(tmp_path)
    try:
        _, graph = build_file_display_graph(tmp_path, image_path=tmp_path / "image.jpg")
        assert "values" in build_ancestor_node_ids(template=graph, target_node_id="preview")
        doc = graph.model_dump(mode="json")
        next(n for n in doc["nodes"] if n["node_id"] == "values")["enabled"] = False
        with pytest.raises(ValueError, match="Presentation.*已禁用"):
            validate_workflow_graph_template(template=WorkflowGraphTemplate.model_validate(doc), node_definitions=catalog.get_workflow_node_definitions())
    finally:
        service.session_factory.engine.dispose()


def test_connected_null_presentation_is_not_treated_as_disconnected():
    """上游返回空值必须明确失败，不能静默关闭面板。"""
    from backend.service.application.workflows.execution.inputs import resolve_node_inputs
    with pytest.raises(InvalidRequestError, match="已连接的 Presentation"):
        resolve_node_inputs(node_id="image", node_definition=image_preview.CORE_NODE_SPEC.node_definition,
            input_values={}, template_input_bindings={}, edge_bindings={("image", "presentation"): [("display", "body")]},
            node_output_values={("display", "body"): None})
