"""四节点真实 Catalog/GraphExecutor 接线与独立几何真值。"""

from dataclasses import replace

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes._metrology3d_nodes.backend.entry import HANDLERS
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.point_cloud_support import create_resource_service, options
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_frame import frame_parameters


def box():
    """显式物理 ROI 覆盖解析平面 z=3。"""
    return dict(
        roi_id="area",
        frame_id="fixture",
        length_unit="mm",
        kind="box",
        geometry=dict(
            center=[1.5, 2.5, 3], size=[2, 2, 2], rotation=np.eye(3).tolist()
        ),
    )


def geometry_graph(
    roi, plane=None, frame=None, *, source="parameters", read=True, preview=False
):
    """与完整样本共用真实节点图，不调用 handler 替代执行器。"""
    nodes = {
        "crop": (
            "crop-roi",
            dict(
                source=dict(
                    kind=source, **({"roi": roi} if source == "parameters" else {})
                )
            ),
        ),
        "plane": (
            "fit-plane",
            dict(
                settings=plane
                or plane_parameters(feature_id="primary").model_dump(mode="json")
            ),
        ),
        "frame": (
            "build-frame",
            dict(settings=frame or frame_parameters().model_dump(mode="json")),
        ),
        "transform": ("transform-cloud", {}),
    }
    links = [
        ("crop", "cloud", "plane", "cloud"),
        ("plane", "features", "frame", "features"),
        ("crop", "cloud", "transform", "cloud"),
        ("frame", "pose", "transform", "pose"),
    ]
    inputs = []
    if read:
        nodes["read"] = (
            "read-cloud",
            dict(
                source=dict(kind="file"), file_options=options().model_dump(mode="json")
            ),
        )
        links.append(("read", "cloud", "crop", "cloud"))
        inputs.append(("file", "file-ref.v1", "read", "file"))
    else:
        inputs.append(("cloud", "point-cloud-ref.v1", "crop", "cloud"))
    if source == "input":
        inputs.append(("roi", "roi3d.v1", "crop", "roi"))
    outputs = [
        ("cloud", "point-cloud-ref.v1", "transform", "cloud"),
        ("pose", "pose3d.v1", "frame", "pose"),
        ("found", "boolean.v1", "frame", "found"),
        ("features", "features3d.v1", "plane", "features"),
        ("cropped", "point-cloud-ref.v1", "crop", "cloud"),
    ]
    if preview:
        nodes["preview"] = (
            "cloud-preview",
            dict(point_limit=2, color=dict(mode="solid")),
        )
        links.extend(
            [
                ("crop", "cloud", "preview", "cloud"),
                ("plane", "features", "preview", "features"),
                ("frame", "pose", "preview", "pose"),
            ]
        )
        outputs.append(("body", "response-body.v1", "preview", "body"))
    return WorkflowGraphTemplate.model_validate(
        dict(
            template_id="geometry-test",
            template_version="0.1.8",
            display_name="Geometry",
            nodes=[
                dict(node_id=k, node_type_id="custom.metrology3d." + t, parameters=p)
                for k, (t, p) in nodes.items()
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
                    output_id=k,
                    display_name=k,
                    payload_type_id=t,
                    source_node_id=n,
                    source_port=p,
                )
                for k, t, n, p in outputs
            ],
        )
    )


@pytest.mark.parametrize("source", ["parameters", "input"])
def test_four_nodes_success_failure_success_and_cleanup(tmp_path, source):
    """两入口与连续失败状态，期望坐标来自解析式而非被测矩阵。"""
    service = create_resource_service(tmp_path)
    configured = execution_policy()
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=service.storage,
        point_cloud_policy=configured,
    )
    registry, _ = build_chain()
    metadata = dict(project_id="test", workflow_run_id="geometry-run")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="geometry-run", policy=configured.io)
    graph = geometry_graph(box(), source=source, preview=True)
    try:
        previous = None
        for good in (True, False, True):
            body = (
                b"1 2 3\n1 3 3\n2 2 3\n2 3 3\n"
                if good
                else b"1 2 3\n1.1 2 3\n1.2 2 3\n1.3 2 3\n"
            )
            inputs = {"file": publish(service.storage, ply(body, count=4))}
            if source == "input":
                inputs["roi"] = box()
            result = WorkflowGraphExecutor(registry=registry).execute(
                template=graph,
                input_values=inputs,
                execution_metadata=metadata,
                runtime_context=context,
            )
            assert len(result.node_records) == 6
            from backend.contracts.workflows.geometry3d_preview import GeometryPreview

            display = GeometryPreview.model_validate(result.outputs["body"]["geometry"])
            assert display.planes[0].valid == good
            assert (display.frame.transform is not None) == good
            assert display.planes[0].support_bounds.min == (1, 2, 3)
            assert display.rois[0].roi_id == "area"
            assert '"cloud_id"' not in display.model_dump_json()
            corrupted = display.model_dump(mode="json")
            corrupted["planes"][0]["support_point_count"] += 1
            with pytest.raises(ValueError, match="支持计数"):
                GeometryPreview.model_validate(corrupted)
            assert result.outputs["found"] == {"value": good}
            cloud = result.outputs["cloud"]
            assert cloud["observation_id"] != previous
            previous = cloud["observation_id"]
            if good:
                from backend.contracts.workflows.point_cloud_runtime import (
                    CloudReference,
                )

                with runtime.borrow(CloudReference.model_validate(cloud)) as view:
                    np.testing.assert_allclose(
                        np.concatenate(
                            [view.chunk(i, i + 2)["positions"] for i in (0, 2)]
                        ),
                        [[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0]],
                        atol=1e-12,
                    )
                    np.testing.assert_array_equal(
                        np.concatenate([view.source_indices(i, i + 2) for i in (0, 2)]),
                        [0, 1, 2, 3],
                    )
            else:
                assert cloud["state"] == "unavailable" and cloud["cloud_id"] is None
                assert result.outputs["pose"]["transform"] is None
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_roi_conflicting_missing_and_invalid_dependencies(tmp_path):
    """来源冲突不能覆盖参数，输入缺失或越坐标依赖都明确拒绝。"""
    service = create_resource_service(tmp_path)
    metadata = dict(project_id="test", workflow_run_id="source-check")
    request = WorkflowNodeExecutionRequest(
        node_id="crop",
        node_definition=object(),
        parameters=dict(source=dict(kind="parameters", roi=box())),
        input_values={"roi": box()},
        execution_metadata=metadata,
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=None,
            dataset_storage=service.storage,
            point_cloud_policy=execution_policy(),
        ),
    )
    try:
        with pytest.raises(InvalidRequestError, match="参数来源"):
            HANDLERS["crop-roi"](request)
        with pytest.raises(ValueError):
            HANDLERS["crop-roi"](
                replace(
                    request, parameters=dict(source=dict(kind="input")), input_values={}
                )
            )
        from custom_nodes._metrology3d_nodes.shared.geometry_parameters import (
            CropNodeParameters,
        )

        band = dict(
            roi_id="slice",
            frame_id="fixture",
            length_unit="mm",
            kind="section-band",
            geometry=dict(
                origin=[0, 0, 3], normal=[0, 0, 1], thickness=1, bounds_roi_id="area"
            ),
        )
        CropNodeParameters(source=dict(kind="parameters", roi=band, bounds=[box()]))
        with pytest.raises(ValueError):
            CropNodeParameters(source=dict(kind="parameters", roi=band, bounds=[]))
        with pytest.raises(ValueError):
            CropNodeParameters(source=dict(kind="input", bounds=[band]))
    finally:
        assert not get_or_create_workflow_resource_scope(metadata).close()


def test_three_datum_ports_preserve_identity_and_analytic_origin(tmp_path):
    """三条真实特征边进入 multiple 端口，原点真值为 (1,2,3)。"""
    service = create_resource_service(tmp_path)
    configured = execution_policy()
    metadata = dict(project_id="test", workflow_run_id="three-datums")
    scope = get_or_create_workflow_resource_scope(metadata)
    context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=service.storage,
        point_cloud_policy=configured,
    )
    primary = box()
    primary["geometry"].update(center=[5.5, 5.5, 3], size=[1, 1, 1])
    settings = frame_parameters().model_dump(mode="json")
    settings["origin"] = dict(kind="three-planes", tertiary_feature_id="tertiary")
    settings["x_axis"] = dict(
        kind="plane-intersection",
        secondary_feature_id="secondary",
        positive_direction=[1, 0, 0],
    )
    settings["quality_policy"]["rules"].append(
        dict(item_id="origin_condition", unit="1", upper=2)
    )
    document = geometry_graph(primary, frame=settings).model_dump(mode="json")
    for name, center, normal in (
        ("secondary", [5.5, 2, 5.5], [0, 1, 0]),
        ("tertiary", [1, 5.5, 5.5], [1, 0, 0]),
    ):
        roi = box()
        roi["roi_id"] = name
        roi["geometry"].update(center=center, size=[1, 1, 1])
        document["nodes"].extend(
            [
                dict(
                    node_id=name + "-crop",
                    node_type_id="custom.metrology3d.crop-roi",
                    parameters=dict(source=dict(kind="parameters", roi=roi)),
                ),
                dict(
                    node_id=name,
                    node_type_id="custom.metrology3d.fit-plane",
                    parameters=dict(
                        settings=plane_parameters(
                            feature_id=name, positive_normal=normal
                        ).model_dump(mode="json")
                    ),
                ),
            ]
        )
        for a, b, c, d in (
            ("read", "cloud", name + "-crop", "cloud"),
            (name + "-crop", "cloud", name, "cloud"),
            (name, "features", "frame", "features"),
        ):
            document["edges"].append(
                dict(
                    edge_id=f"{a}-{c}",
                    source_node_id=a,
                    source_port=b,
                    target_node_id=c,
                    target_port=d,
                )
            )
    points = (
        [(x, y, 3) for x in (5, 6) for y in (5, 6)]
        + [(x, 2, z) for x in (5, 6) for z in (5, 6)]
        + [(1, y, z) for y in (5, 6) for z in (5, 6)]
    )
    file = publish(
        service.storage,
        ply(("".join(f"{x} {y} {z}\n" for x, y, z in points)).encode(), count=12),
    )
    registry, _ = build_chain()
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=WorkflowGraphTemplate.model_validate(document),
            input_values={"file": file},
            execution_metadata=metadata,
            runtime_context=context,
        )
        assert result.outputs["found"] == {"value": True}
        np.testing.assert_allclose(
            result.outputs["pose"]["transform"]["matrix"],
            [[1, 0, 0, -1], [0, 1, 0, -2], [0, 0, 1, -3], [0, 0, 0, 1]],
            atol=1e-12,
        )
        assert len(result.outputs["pose"]["support"]) == 3
        for node in document["nodes"]:
            if node["node_id"] == "secondary":
                node["parameters"]["settings"]["feature_id"] = "primary"
        with pytest.raises(InvalidRequestError):
            WorkflowGraphExecutor(registry=registry).execute(
                template=WorkflowGraphTemplate.model_validate(document),
                input_values={"file": file},
                execution_metadata=metadata,
                runtime_context=context,
            )
    finally:
        assert not scope.close()
