"""验收配方的数值交付接线；只组合已有节点，不实现新的聚合或测量算法。"""


def connect_measurement_output(graph, sources):
    """把测量表接到正式响应和数值预览，三维显示保持独立分支。"""
    graph["nodes"].extend(
        [
            dict(node_id="results", node_type_id="core.value.numeric-tables-merge"),
            dict(node_id="values", node_type_id="core.value.numeric-table-to-value"),
            dict(
                node_id="response",
                node_type_id="core.output.response-envelope",
                parameters=dict(code=0, message="measured"),
            ),
            dict(
                node_id="table",
                node_type_id="core.io.value-preview",
                parameters=dict(
                    title="Measurements",
                    display_mode="table",
                    path="items",
                    columns=[
                        dict(key=key, label=label, format=kind)
                        for key, label, kind in (
                            ("item_id", "Item", "value"),
                            ("value", "Value", "value"),
                            ("unit", "Unit", "unit"),
                            ("valid", "Valid", "validity"),
                            ("reason", "Reason", "reason"),
                        )
                    ],
                ),
            ),
        ]
    )
    connections = [(source, "measurements", "results", "tables") for source in sources]
    connections.extend(
        [
            ("results", "table", "values", "table"),
            ("values", "value", "response", "data"),
            ("values", "value", "table", "value"),
        ]
    )
    graph["edges"].extend(
        dict(
            edge_id=f"numeric-{index}",
            source_node_id=a,
            source_port=b,
            target_node_id=c,
            target_port=d,
        )
        for index, (a, b, c, d) in enumerate(connections)
    )
    graph["template_outputs"] = [
        dict(
            output_id="body",
            display_name="Measurements",
            payload_type_id="response-body.v1",
            source_node_id="response",
            source_port="body",
        )
    ]
