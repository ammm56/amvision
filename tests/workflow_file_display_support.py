"""用通用节点组装记录/汇总/显示示例，不依赖现场类别名称。"""

from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)


def build_file_display_graph(
    root: Path, *, total: int = 24, image_path: Path | None = None
):
    """构造可直接在隔离 Preview 或 Runtime 验证的标准 v1 文档。"""
    nodes, edges = [], []

    def node(identity, kind, **parameters):
        nodes.append(dict(node_id=identity, node_type_id=kind, parameters=parameters))
        return identity

    def edge(source, port, target, input_port):
        edges.append(
            dict(
                edge_id=f"e{len(edges)}",
                source_node_id=source,
                source_port=port,
                target_node_id=target,
                target_port=input_port,
            )
        )

    def extract(identity, source, port, path):
        node(identity, "core.logic.value-field-extract", path=path)
        edge(source, port, identity, "value")
        return identity

    def field(identity, source, port, key, target):
        node(identity, "core.logic.object-field", key=key)
        edge(source, port, identity, "value")
        edge(identity, "field", target, "entries")

    node(
        "counts",
        "core.logic.count-by-rules",
        rules=[
            {
                "key": "ok",
                "condition": {
                    "operator": "in",
                    "path": "label",
                    "right": ["acceptable-a", "acceptable-b"],
                },
            },
            {
                "key": "ng",
                "condition": {
                    "operator": "in",
                    "path": "label",
                    "right": ["defect-a", "defect-b", "unknown", "missing"],
                },
            },
        ],
    )
    node(
        "record",
        "core.logic.object-build",
        fields={"material_total": total},
    )
    for key in ("ok", "ng"):
        source = extract("count_" + key, "counts", "counts", key)
        field("field_" + key, source, "value", "material_" + key, "record")
    node(
        "append",
        "core.output.jsonl-append-local",
        save_location=str(root / "records.jsonl"),
    )
    edge("record", "value", "append", "value")
    extract("log_path", "append", "receipt", "file.local_path")
    node(
        "summary",
        "core.io.file-summary",
        state_path=str(root / "summary.json"),
        reducers=[
            {"output_key": key, "source_path": key, "operation": "sum"}
            for key in ("material_total", "material_ok", "material_ng")
        ]
        + [{"output_key": "tray_total", "operation": "count"}],
    )
    edge("log_path", "value", "summary", "path")
    extract("context", "summary", "snapshot", "source")
    extract("total", "summary", "snapshot", "totals.material_total")
    extract("ok", "summary", "snapshot", "totals.material_ok")
    node("yield", "core.logic.number-operation", operation="divide")
    edge("ok", "value", "yield", "left")
    edge("total", "value", "yield", "right")
    node("presentation", "core.logic.object-build", fields={})
    field("summary_field", "summary", "snapshot", "summary", "presentation")
    field("yield_field", "yield", "value", "yield", "presentation")
    node(
        "values",
        "core.io.value-display",
        fields=[
            {"path": "summary.totals." + key, "label": label, "format": "integer"}
            for key, label in (
                ("material_total", "总产量"),
                ("material_ok", "OK"),
                ("material_ng", "NG"),
            )
        ]
        + [{"path": "yield", "label": "良品率", "format": "percent", "precision": 2}],
    )
    edge("presentation", "value", "values", "value")
    edge("context", "value", "values", "context")
    displays = [
        {"node_id": "values", "output_port": "body", "title": "结果", "size": "medium"}
    ]
    if image_path:
        node("image", "core.io.image-load-local", local_path=str(image_path))
        node("preview", "core.io.image-preview")
        edge("image", "image", "preview", "image")
        edge("context", "value", "preview", "presentation_context")
        displays = [
            {
                "node_id": "preview",
                "output_port": "body",
                "title": "检测结果",
                "size": "large",
                "overlay": {
                    "node_id": "values",
                    "output_port": "body",
                    "position": "top-left",
                },
            }
        ]
    template = WorkflowGraphTemplate.model_validate(
        dict(
            template_id="workflow-file-display-test",
            template_version="1.0.0",
            display_name="通用记录显示验证",
            nodes=nodes,
            edges=edges,
            template_inputs=[
                dict(
                    input_id="items",
                    display_name="Items",
                    payload_type_id="value.v1",
                    target_node_id="counts",
                    target_port="items",
                )
            ],
            template_outputs=[
                dict(
                    output_id="result",
                    display_name="Result",
                    payload_type_id="value.v1",
                    source_node_id="summary",
                    source_port="snapshot",
                )
            ],
        )
    )
    application = FlowApplication.model_validate(
        dict(
            application_id="workflow-app-file-display-test",
            display_name="通用记录显示验证",
            template_ref=dict(
                template_id=template.template_id,
                template_version="1.0.0",
                source_kind="json-file",
                source_uri="test/template.json",
            ),
            bindings=[
                dict(
                    binding_id="items",
                    direction="input",
                    template_port_id="items",
                    binding_kind="api-request",
                    metadata={"payload_type_id": "value.v1"},
                ),
                dict(
                    binding_id="result",
                    direction="output",
                    template_port_id="result",
                    binding_kind="http-response",
                    metadata={"payload_type_id": "value.v1"},
                ),
            ],
            metadata={
                "app_mode": {
                    "format_id": "amvision.workflow-app-mode.v1",
                    "title": "",
                    "displays": displays,
                }
            },
        )
    )
    return application, template
