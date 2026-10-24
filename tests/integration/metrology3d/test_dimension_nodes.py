"""三个尺寸节点的实际 Catalog/GraphExecutor 和解析几何验收。"""

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    evaluation,
    line_parameters,
)
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_dimension_runtime import hole_parameters
from tests.test_metrology3d_edge_pair import pair_parameters
from tests.test_metrology3d_preview import preview_policy
from tests.test_point_cloud_trigger import descriptor


def dimension_documents(kind, *, file=False):
    """完整真实配方；仅数据和测试参数变化，不替代运行准入。"""
    template, app = cloud_documents(options().model_dump(mode="json") if file else None)
    graph = template.model_dump(mode="json")

    def node(name, kind, p):
        graph["nodes"].append(
            dict(
                node_id=name,
                node_type_id="custom.metrology3d." + kind,
                parameters=dict(settings=p.model_dump(mode="json")),
            )
        )

    def link(a, b, c, d):
        graph["edges"].append(
            dict(
                edge_id=f"dimension-{len(graph['edges'])}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )

    if kind == "extents":
        points = np.array([(x, y, 0) for x in range(9) for y in range(4)], dtype="<f4")
        node("dimension", "measure-extents", extent_parameters(rectangle=True))
        link("filter", "cloud", "dimension", "cloud")
    elif kind == "edge-pair":
        points = np.array(
            [
                (x + offset, y, x)
                for offset in (0, 4)
                for x in range(3)
                for y in range(-2, 3)
            ],
            dtype="<f4",
        )
        plane = evaluation(origin=(0, 0, 0.5))
        extraction = extract_parameters(
            evaluation=plane,
            method=dict(
                kind="section",
                origin=(0, 0, 0.5),
                normal=(0, 0, 1),
                numeric_tolerance=1e-10,
            ),
            targets=[
                dict(
                    segment_id=key,
                    closed=False,
                    role="open",
                    region=region(center=(x, 0, 0.5), size=(1, 6, 1)),
                )
                for key, x in (("left", 0.5), ("right", 4.5))
            ],
        )
        node("extract", "extract-boundary", extraction)
        link("filter", "cloud", "extract", "cloud")
        for name, segment in (("a", "left"), ("b", "right")):
            node(
                name,
                "fit-line",
                line_parameters(
                    feature_id=name,
                    selection=dict(feature_id="boundary", segment_ids=[segment]),
                    evaluation=plane,
                    positive_direction=(0, 1, 0),
                ),
            )
            link("extract", "features", name, "features")
            link(name, "features", "dimension", "features")
            link(name, "features", "preview", "features")
        p = pair_parameters().model_copy(
            update={"evaluation": plane, "query_position": (0, 0, 0.5)}
        )
        node("dimension", "measure-edge-pair", p)
    else:
        angle = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        points = np.vstack(
            [
                np.column_stack((r * np.cos(angle), r * np.sin(angle), np.zeros(64)))
                for r in (4, 5, 6)
            ]
        ).astype("<f4")
        extraction = extract_parameters(
            surface=dict(
                alpha_radius=0.8,
                max_edge_length=1.5,
                max_normal_step=0.1,
                min_projected_area=1e-8,
            ),
            targets=[
                dict(
                    segment_id="arc",
                    closed=True,
                    role="inner",
                    region=region(size=(9.5, 9.5, 2)),
                )
            ],
        )
        node("extract", "extract-boundary", extraction)
        node("circle", "fit-circle", circle_parameters())
        node("dimension", "measure-hole", hole_parameters())
        for a, b, c, d in (
            ("filter", "cloud", "extract", "cloud"),
            ("extract", "features", "circle", "features"),
            ("circle", "features", "dimension", "features"),
            ("circle", "features", "preview", "features"),
        ):
            link(a, b, c, d)
    link("dimension", "evidence", "preview", "evidence")
    graph["template_outputs"].append(
        dict(
            output_id="measurements",
            display_name="Dimensions",
            payload_type_id="numeric-table.v1",
            source_node_id="dimension",
            source_port="measurements",
        )
    )
    cloud = descriptor().model_dump(mode="json")
    cloud.update(point_count=len(points), content_length=points.nbytes)
    cloud["fields"][0].update(count=len(points), byte_length=points.nbytes)
    cloud["spatial"]["frame_id"] = "fixture"
    return (WorkflowGraphTemplate.model_validate(graph), app), cloud, points


def check_dimensions(body, kind):
    """解析尺寸 8x3、两边距离4、孔径8，不以算法输出当真值。"""
    evidence = MeasurementEvidence3d.model_validate(body["measurements"])
    assert all(i.valid for i in evidence.items), evidence
    expected = (
        [8, 3] if kind == "extents" else [4] if kind == "edge-pair" else [8, 0, 0, 0]
    )
    np.testing.assert_allclose([i.value for i in evidence.items], expected, atol=2e-6)
    assert "cloud_id" not in evidence.model_dump_json()


@pytest.mark.parametrize("kind", ["extents", "edge-pair", "hole"])
def test_dimension_graph_file_input_and_display(tmp_path, kind):
    documents, _, points = dimension_documents(kind, file=True)
    service = create_resource_service(tmp_path)
    configured = execution_policy().model_copy(
        update={
            "io": policy(
                max_working_bytes=10_000_000,
                max_decoded_bytes=1_000_000,
                max_live_array_bytes=1_000_000,
            ),
            "preview": preview_policy(
                max_points=1000, max_data_bytes=131072, max_body_bytes=1000000
            ),
        }
    )
    metadata = dict(project_id="test", workflow_run_id="dimension-graph")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="dimension-graph", policy=configured.io)
    registry, _ = build_chain()
    try:
        file = publish(
            service.storage,
            ply(
                "".join(f"{x:.9g} {y:.9g} {z:.9g}\n" for x, y, z in points).encode(),
                count=len(points),
            ),
        )
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=documents[0],
            input_values={"input": file},
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=configured,
            ),
        )
        body = result.outputs["body"]
        check_dimensions(body, kind)
        assert result.outputs["measurements"] == MeasurementEvidence3d.model_validate(
            body["measurements"]
        ).numeric_table().model_dump(mode="json")
    finally:
        assert not scope.close() and runtime.budget.used == 0
