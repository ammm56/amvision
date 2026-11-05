"""局部配准正式图：双文件/双资产，标准位姿、变换、显示链。"""

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.test_metrology3d_registration import settings


def registration_documents(*, assets=None, parameters=None, registration_stride=None):
    """所有数值为解析测试实例；业务配方必须按实际坐标/质量显式配置。"""
    template, application = cloud_documents(options().model_dump(mode="json"))
    graph, app = template.model_dump(mode="json"), application.model_dump(mode="json")
    reference_options = options().model_dump(mode="json")
    reference_options["spatial"]["frame_id"] = "reference"
    graph["nodes"].extend(
        [
            dict(
                node_id="reference",
                node_type_id="custom.metrology3d.read-cloud",
                parameters=dict(
                    source=dict(kind="file"), file_options=reference_options
                ),
            ),
            dict(
                node_id="register",
                node_type_id="custom.metrology3d.register-cloud",
                parameters=dict(
                    settings=(parameters or settings()).model_dump(mode="json")
                ),
            ),
            dict(
                node_id="aligned",
                node_type_id="custom.metrology3d.transform-cloud",
                parameters={},
            ),
        ]
    )
    graph["edges"] = [e for e in graph["edges"] if e["target_node_id"] != "preview"]
    for i, (a, b, c, d) in enumerate(
        [
            ("filter", "cloud", "register", "source"),
            ("reference", "cloud", "register", "reference"),
            ("filter", "cloud", "aligned", "cloud"),
            ("register", "pose", "aligned", "pose"),
            ("aligned", "cloud", "preview", "cloud"),
            ("register", "pose", "preview", "pose"),
        ]
    ):
        graph["edges"].append(
            dict(
                edge_id=f"registration-{i}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )
    graph["template_inputs"].append(
        dict(
            input_id="reference",
            display_name="Reference",
            payload_type_id="file-ref.v1",
            target_node_id="reference",
            target_port="file",
        )
    )
    app["bindings"].append(
        dict(
            binding_id="reference",
            direction="input",
            template_port_id="reference",
            binding_kind="api-request",
            config=dict(
                allowed_media_types=["application/octet-stream"],
                max_file_bytes=1_000_000_000,
            ),
        )
    )
    if assets:
        for key, asset in zip(("read", "reference"), assets, strict=True):
            next(n for n in graph["nodes"] if n["node_id"] == key)["parameters"] = dict(
                source=dict(kind="asset", reference=asset.model_dump(mode="json"))
            )
        graph["template_inputs"] = []
        app["bindings"] = [b for b in app["bindings"] if b["direction"] == "output"]
    if registration_stride is not None:
        for original, key in (
            ("filter", "source-sample"),
            ("reference", "reference-sample"),
        ):
            graph["nodes"].append(
                dict(
                    node_id=key,
                    node_type_id="custom.metrology3d.resample-cloud",
                    parameters=dict(
                        settings=dict(
                            kind="stride", every_k_points=registration_stride, offset=0
                        )
                    ),
                )
            )
            for edge in graph["edges"]:
                if (
                    edge["source_node_id"] == original
                    and edge["target_node_id"] == "register"
                ):
                    edge["source_node_id"] = key
            graph["edges"].append(
                dict(
                    edge_id=key,
                    source_node_id=original,
                    source_port="cloud",
                    target_node_id=key,
                    target_port="cloud",
                )
            )
    for i, node in enumerate(graph["nodes"]):
        node["ui_state"] = dict(x=40 + (i % 3) * 480, y=40 + (i // 3) * 570)
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        app
    )
