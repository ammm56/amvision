"""三节点及边界保存重读沿真实 GraphExecutor 执行，不用 handler 代替图准入。"""

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)
from tests.integration.metrology3d.test_boundary_runtime import runtime_policy
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    line_parameters,
    evaluation,
)
from tests.point_cloud_support import create_resource_service, options


def graph(nodes, links, outputs, file=True):
    """使用真实公开端口构造测试配方。"""
    return WorkflowGraphTemplate.model_validate(
        dict(
            template_id="boundary",
            template_version="0.1.8",
            display_name="Boundary",
            nodes=[
                dict(node_id=n, node_type_id="custom.metrology3d." + k, parameters=p)
                for n, k, p in nodes
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
                    input_id="file",
                    display_name="File",
                    payload_type_id="file-ref.v1",
                    target_node_id="read",
                    target_port="file",
                )
            ]
            if file
            else [],
            template_outputs=[
                dict(
                    output_id=n,
                    display_name=n,
                    payload_type_id=t,
                    source_node_id=a,
                    source_port=b,
                )
                for n, t, a, b in outputs
            ],
        )
    )


@pytest.mark.parametrize("kind", ["line", "circle"])
def test_graph_extract_save_restore_fit(tmp_path, kind):
    """独立解析真值，包含新运行恢复、显示与所有权清理。"""
    service = create_resource_service(tmp_path)
    configured = execution_policy().model_copy(
        update={
            "io": runtime_policy(),
            "max_asset_bytes": 100_000,
            "max_archive_bytes": 200_000,
        }
    )
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=service.storage,
        point_cloud_policy=configured,
    )
    registry, _ = build_chain()
    if kind == "line":
        points = np.array([(x, y, x) for x in range(3) for y in range(3)])
        extract = extract_parameters(
            method=dict(
                kind="section",
                origin=[0, 0, 0.5],
                normal=[0, 0, 1],
                numeric_tolerance=1e-10,
            ),
            targets=[
                dict(segment_id="side", region=region(), closed=False, role="open")
            ],
        )
        fit = line_parameters(
            evaluation=evaluation(
                origin=[0.5, 0, 0.5], rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]]
            ),
            positive_direction=[0, 1, 0],
        )
    else:
        angle = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        points = np.vstack(
            (
                [[0, 0, 0]],
                np.column_stack((4 * np.cos(angle), 4 * np.sin(angle), np.zeros(64))),
            )
        )
        extract = extract_parameters(
            surface=dict(
                alpha_radius=5,
                max_edge_length=9,
                max_normal_step=1,
                min_projected_area=1e-12,
            ),
            targets=[
                dict(segment_id="arc", region=region(), closed=True, role="outer")
            ],
        )
        fit = circle_parameters()
    initial = graph(
        [
            (
                "read",
                "read-cloud",
                dict(
                    source=dict(kind="file"),
                    file_options=options().model_dump(mode="json"),
                ),
            ),
            (
                "extract",
                "extract-boundary",
                dict(settings=extract.model_dump(mode="json")),
            ),
            (
                "save",
                "save-cloud",
                dict(mode="derived", target=dict(kind="new", name="Boundary")),
            ),
        ],
        [
            ("read", "cloud", "extract", "cloud"),
            ("extract", "cloud", "save", "cloud"),
            ("extract", "features", "save", "features"),
        ],
        [("resource", "measurement-resource-ref.v1", "save", "resource")],
    )
    body = "".join(
        " ".join(format(float(v), ".9g") for v in row) + "\n" for row in points
    ).encode()
    metadata = dict(project_id="test", workflow_run_id="first")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="first", policy=configured.io)
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=initial,
            input_values={
                "file": publish(service.storage, ply(body, count=len(points)))
            },
            execution_metadata=metadata,
            runtime_context=context,
        )
        asset = result.outputs["resource"]
    finally:
        assert not scope.close() and runtime.budget.used == 0
    restored = graph(
        [
            ("read", "read-cloud", dict(source=dict(kind="asset", reference=asset))),
            ("fit", "fit-" + kind, dict(settings=fit.model_dump(mode="json"))),
        ],
        [("read", "features", "fit", "features")],
        [("features", "features3d.v2", "fit", "features")],
        file=False,
    )
    metadata = dict(project_id="test", workflow_run_id="second")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="second", policy=configured.io)
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=restored,
            input_values={},
            execution_metadata=metadata,
            runtime_context=context,
        )
        feature = result.outputs["features"]["items"][0]
        assert feature["valid"] and feature["support"]["run_id"] == "second"
        if kind == "circle":
            assert feature["geometry"]["radius"] == pytest.approx(4, abs=1e-6)
        else:
            np.testing.assert_allclose(
                feature["geometry"]["origin"], [0.5, 1, 0.5], atol=1e-12
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0
