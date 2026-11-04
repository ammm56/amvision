"""A08 非工件方法的解析配方；页面与真实发布回归共用。"""

import numpy as np

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from tests.integration.metrology3d.test_geometry_nodes import box, three_datum_graph
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.test_metrology3d_measurement_contracts import step_parameters


def method_documents(kind):
    """构造独立真值，不以图执行输出生成预期值或测试参数。"""
    template, app = cloud_documents(options().model_dump(mode="json"))
    if kind == "three-planes":
        template, points = three_datum_graph(preview=True)
        graph = template.model_dump(mode="json")
        graph["template_inputs"][0]["input_id"] = "input"
        graph["template_outputs"] = [
            p for p in graph["template_outputs"] if p["output_id"] == "body"
        ]
        for node in graph["nodes"]:
            if node["node_id"] == "preview":
                node["parameters"]["point_limit"] = 100
    elif kind.startswith("denoise-"):
        from tests.test_metrology3d_denoise import points as denoise_points, parameters

        points = denoise_points()
        graph = template.model_dump(mode="json")
        graph["nodes"].append(
            dict(
                node_id="denoise",
                node_type_id="custom.metrology3d.denoise-cloud",
                parameters=parameters(kind.removeprefix("denoise-")).model_dump(
                    mode="json"
                ),
            )
        )
        for edge in graph["edges"]:
            if edge["target_node_id"] == "preview" and edge["target_port"] == "cloud":
                edge["source_node_id"] = "denoise"
        graph["edges"].append(
            dict(
                edge_id="denoise-input",
                source_node_id="filter",
                source_port="cloud",
                target_node_id="denoise",
                target_port="cloud",
            )
        )
    else:
        assert kind in ("statistic-mean", "statistic-median", "statistic-quantile")
        statistic = {"kind": kind.removeprefix("statistic-")}
        if statistic["kind"] == "quantile":
            statistic.update(probability=0.75, method="linear")
        # 同 XY 的四点支持，Z 分别为 0/1/2/3 和 5/6/7/8，各统计高差均为5。
        points = [
            (i % 2, i // 2, z + shift)
            for shift in (0, 5)
            for i, z in enumerate(range(4))
        ]
        graph = template.model_dump(mode="json")
        for name, center in (("reference", 1.5), ("target", 6.5)):
            roi = box()
            roi.update(roi_id=name)
            roi["geometry"].update(center=[0.5, 0.5, center], size=[2, 2, 3.5])
            graph["nodes"].append(
                dict(
                    node_id=name,
                    node_type_id="custom.metrology3d.crop-roi",
                    parameters=dict(source=dict(kind="parameters", roi=roi)),
                )
            )
            graph["edges"].extend(
                [
                    dict(
                        edge_id="input-" + name,
                        source_node_id="filter",
                        source_port="cloud",
                        target_node_id=name,
                        target_port="cloud",
                    ),
                    dict(
                        edge_id="step-" + name,
                        source_node_id=name,
                        source_port="cloud",
                        target_node_id="step",
                        target_port=name,
                    ),
                ]
            )
        graph["nodes"].append(
            dict(
                node_id="step",
                node_type_id="custom.metrology3d.measure-step",
                parameters=dict(
                    settings=step_parameters(statistic=statistic).model_dump(
                        mode="json"
                    )
                ),
            )
        )
        graph["edges"].append(
            dict(
                edge_id="evidence",
                source_node_id="step",
                source_port="evidence",
                target_node_id="preview",
                target_port="evidence",
            )
        )
    graph.update(template_id="method-" + kind, display_name=kind)
    template = WorkflowGraphTemplate.model_validate(graph)
    app = app.model_copy(
        update=dict(
            application_id="method-" + kind,
            display_name=kind,
            template_ref=app.template_ref.model_copy(
                update=dict(
                    template_id=template.template_id,
                    template_version=template.template_version,
                )
            ),
        )
    )
    return (template, app), np.asarray(points, dtype="<f4")
