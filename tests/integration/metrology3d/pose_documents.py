"""B05 位姿发布图；沿正式文件/资产入口，不改原工件测量配方。"""

from pathlib import Path
import json
from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.integration.metrology3d.test_geometry_nodes import box
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_frame import frame_parameters


def pose_documents(*, reference=None, complete=False):
    """完整工件沿既有台面五窗及质量限值，小样本使用独立解析平面。"""
    template, app = cloud_documents(options().model_dump(mode="json"))
    graph = template.model_dump(mode="json")
    if complete:
        file = (
            Path(__file__).resolve().parents[3]
            / "docs/examples/workflows/lithium_workpiece.template.json"
        )
        nodes = {n["node_id"]: n for n in json.loads(file.read_text("utf-8"))["nodes"]}
        datum = [nodes[k] for k in ("D-crop", "D", "frame")]
    else:
        datum = [
            dict(
                node_id="D-crop",
                node_type_id="custom.metrology3d.crop-roi",
                parameters=dict(source=dict(kind="parameters", roi=box())),
            ),
            dict(
                node_id="D",
                node_type_id="custom.metrology3d.fit-plane",
                parameters=dict(
                    settings=plane_parameters(feature_id="primary").model_dump(
                        mode="json"
                    )
                ),
            ),
            dict(
                node_id="frame",
                node_type_id="custom.metrology3d.build-frame",
                parameters=dict(settings=frame_parameters().model_dump(mode="json")),
            ),
        ]
    graph["nodes"].extend(datum)
    for key, kind, parameters in (
        ("inverse", "invert-pose", dict(settings=dict(pose_id="inverse"))),
        ("identity", "compose-pose", dict(settings=dict(pose_id="identity"))),
        ("forward", "transform-cloud", {}),
        ("restored", "transform-cloud", {}),
    ):
        graph["nodes"].append(
            dict(
                node_id=key,
                node_type_id="custom.metrology3d." + kind,
                parameters=parameters,
            )
        )
    graph["edges"] = [e for e in graph["edges"] if e["target_node_id"] != "preview"]
    for i, (a, b, c, d) in enumerate(
        (
            ("filter", "cloud", "D-crop", "cloud"),
            ("D-crop", "cloud", "D", "cloud"),
            ("D", "features", "frame", "features"),
            ("frame", "pose", "inverse", "pose"),
            ("frame", "pose", "identity", "first"),
            ("inverse", "pose", "identity", "second"),
            ("filter", "cloud", "forward", "cloud"),
            ("frame", "pose", "forward", "pose"),
            ("forward", "cloud", "restored", "cloud"),
            ("inverse", "pose", "restored", "pose"),
            ("restored", "cloud", "preview", "cloud"),
            ("identity", "pose", "preview", "pose"),
        )
    ):
        graph["edges"].append(
            dict(
                edge_id=f"pose-{i}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )
    for i, n in enumerate(graph["nodes"]):
        n["ui_state"] = dict(x=40 + (i % 4) * 480, y=40 + (i // 4) * 570)
    if reference is not None:
        next(n for n in graph["nodes"] if n["node_id"] == "read")["parameters"] = dict(
            source=dict(kind="asset", reference=reference.model_dump(mode="json"))
        )
        graph["template_inputs"] = []
        raw = app.model_dump(mode="json")
        raw["bindings"] = [b for b in raw["bindings"] if b["direction"] == "output"]
        app = FlowApplication.model_validate(raw)
    return WorkflowGraphTemplate.model_validate(graph), app
