"""真实 Catalog/GraphExecutor 接通测量、数值表及持久三维证据。"""

import numpy as np

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_measurement_contracts import (
    height_parameters,
    step_parameters,
)
from tests.test_metrology3d_preview import preview_policy


def measurement_graph(*, height=None, reference_roi=None, read=True):
    """完整图复用真实处理器；参数可以由完整样本测试显式提供。"""
    height = height or height_parameters()
    plane = height.plane_fit.model_copy(
        update={"feature_id": height.reference_feature_id}
    )
    step = step_parameters(
        query_position=height.query_position,
        direction=height.direction,
        support_radius=height.support_radius,
        quality_policy=height.quality_policy,
        reference_feature_id=height.reference_feature_id,
        target_feature_id=height.plane_fit.feature_id,
    )
    reference_roi = reference_roi or dict(
        roi_id="reference-roi",
        kind="box",
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(center=[0, 0, 0], size=[4, 4, 2], rotation=np.eye(3).tolist()),
    )
    nodes = {
        "reference": (
            "crop-roi",
            dict(source=dict(kind="parameters", roi=reference_roi)),
        ),
        "plane": ("fit-plane", dict(settings=plane.model_dump(mode="json"))),
        "height": ("height-query", dict(settings=height.model_dump(mode="json"))),
        "step": ("measure-step", dict(settings=step.model_dump(mode="json"))),
        "preview": ("cloud-preview", dict(point_limit=18, color=dict(mode="solid"))),
    }
    links = [
        ("reference", "cloud", "plane", "cloud"),
        ("plane", "features", "height", "features"),
        ("plane", "features", "step", "features"),
        ("height", "features", "step", "features"),
        ("height", "evidence", "preview", "evidence"),
        ("step", "evidence", "preview", "evidence"),
    ]
    links.extend(
        [
            ("plane", "features", "preview", "features"),
            ("height", "features", "preview", "features"),
        ]
    )
    inputs = []
    if read:
        nodes["read"] = (
            "read-cloud",
            dict(
                source=dict(kind="file"), file_options=options().model_dump(mode="json")
            ),
        )
        inputs = [("file", "file-ref.v1", "read", "file")]
        links.extend(
            ("read", "cloud", node, "cloud")
            for node in ("reference", "height", "preview")
        )
    else:
        # 同一个冻结输入分别绑定；测试调用方提供相同只读引用。
        inputs = [
            (f"cloud-{node}", "point-cloud-ref.v2", node, "cloud")
            for node in ("reference", "height", "preview")
        ]
    outputs = [
        ("height", "numeric-table.v1", "height", "measurements"),
        ("step", "numeric-table.v1", "step", "measurements"),
        ("evidence", "measurement-evidence3d.v1", "height", "evidence"),
        ("body", "response-body.v1", "preview", "body"),
    ]
    return WorkflowGraphTemplate.model_validate(
        dict(
            template_id="measurement-test",
            template_version="0.1.8",
            display_name="Measurement",
            nodes=[
                dict(
                    node_id=key, node_type_id="custom.metrology3d." + kind, parameters=p
                )
                for key, (kind, p) in nodes.items()
            ],
            edges=[
                dict(
                    edge_id=str(i),
                    source_node_id=a,
                    source_port=b,
                    target_node_id=c,
                    target_port=d,
                )
                for i, (a, b, c, d) in enumerate(links)
            ],
            template_inputs=[
                dict(
                    input_id=a,
                    display_name=a,
                    payload_type_id=b,
                    target_node_id=c,
                    target_port=d,
                )
                for a, b, c, d in inputs
            ],
            template_outputs=[
                dict(
                    output_id=a,
                    display_name=a,
                    payload_type_id=b,
                    source_node_id=c,
                    source_port=d,
                )
                for a, b, c, d in outputs
            ],
        )
    )


def test_height_and_step_graph_success_failure_success(tmp_path):
    """实际图连续执行，晚一次失败不能输出前一次成功量值。"""
    service = create_resource_service(tmp_path)
    configured = execution_policy().model_copy(
        update={
            "io": policy(max_working_bytes=1024 * 1024),
            "preview": preview_policy(
                max_points=18, max_data_bytes=65536, max_body_bytes=131072
            ),
        }
    )
    metadata = dict(project_id="test", workflow_run_id="height-graph")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="height-graph", policy=configured.io)
    registry, _ = build_chain()
    observations = []
    try:
        for good in (True, False, True):
            points = [
                (x, y, z)
                for z in ((0, 5) if good else (0,))
                for x in (-1, 0, 1)
                for y in (-1, 0, 1)
            ]
            file = publish(
                service.storage,
                ply(
                    ("".join(f"{x} {y} {z}\n" for x, y, z in points)).encode(),
                    count=len(points),
                ),
            )
            result = WorkflowGraphExecutor(registry=registry).execute(
                template=measurement_graph(),
                input_values={"file": file},
                execution_metadata=metadata,
                runtime_context=WorkflowServiceNodeRuntimeContext(
                    session_factory=None,
                    dataset_storage=service.storage,
                    point_cloud_policy=configured,
                ),
            )
            evidence = MeasurementEvidence3d.model_validate(result.outputs["evidence"])
            display = MeasurementEvidence3d.model_validate(
                result.outputs["body"]["measurements"]
            )
            assert display.items[0] == evidence.items[0]
            for name in ("height", "step"):
                item = result.outputs[name]["items"][0]
                assert item["valid"] == good
                assert item["value"] == (5 if good else None)
            assert all(item.valid == good for item in display.items)
            assert result.outputs["body"]["state"] == "ready"
            observations.append(evidence.observation_id)
        assert len(set(observations)) == 3
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
