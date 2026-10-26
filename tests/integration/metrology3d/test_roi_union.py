"""R5 A：并集通过真实节点执行、显示契约和资产保存重读。"""

import numpy as np
import pytest

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.geometry3d_preview import GeometryPreview
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.service.application.runtime.resource_scope import (
    ResourceScope,
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes._metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from tests.integration.metrology3d.test_file_read import ply, publish
from tests.integration.metrology3d.test_geometry_nodes import box, geometry_graph
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.point_cloud_support import create_resource_service, policy
from tests.test_metrology3d_crop import parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_roi_union import boxes, union


def test_union_boundary_selection_keeps_gap_ambiguous():
    """并集不将两条实测边拼成单段，也不让质量门禁退化。"""
    from tests.integration.metrology3d.test_boundary_extraction import (
        extract,
        extract_parameters,
        region,
    )

    members = []
    for key, x in (("left", 0), ("right", 4)):
        roi = region(center=(x, 2, 0), size=(0.2, 2.2, 1))["rois"][0]
        roi["roi_id"] = key
        members.append(roi)
    target = dict(
        segment_id="two-sides",
        closed=False,
        role="open",
        region=dict(roi_id="all", rois=[union("all", "left", "right"), *members]),
    )
    points = np.array([(x, y, 0) for x in range(5) for y in range(5)], dtype="f4")
    result = extract(points, extract_parameters(targets=[target]))
    assert result.reason == "target_ambiguous" and result.positions is None


def test_boundary_roi_does_not_reuse_reserved_geometry_budget():
    """几何工作集和 ROI 单独可放下、合计不足时必须拒绝。"""
    from backend.service.application.errors import InvalidRequestError
    from tests.integration.metrology3d.test_boundary_extraction import extract

    points = np.array([(x, y, 0) for x in range(5) for y in range(5)], dtype="f4")
    with pytest.raises(InvalidRequestError, match="预算"):
        extract(points, max_working_bytes=len(points) * 12288 + 100)


@pytest.mark.parametrize("source", ["parameters", "input"])
def test_union_graph_to_plane_and_preview(tmp_path, source):
    """双入口同一闭合集合，预览和拟合消费真实行号而非分别拼接。"""
    service = create_resource_service(tmp_path)
    configured = execution_policy()
    metadata = dict(project_id="test", workflow_run_id="union-graph")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(scope, run_id="union-graph", policy=configured.io)
    root = union("all", "left", "right")
    members = []
    for key, x in (("left", 1), ("right", 2)):
        roi = box()
        roi["roi_id"] = key
        roi["geometry"].update(center=[x, 2.5, 3], size=[0.5, 2, 2])
        members.append(roi)
    unused = box()
    unused["roi_id"] = "unused"
    members.append(unused)
    document = geometry_graph(root, source=source, preview=True).model_dump(mode="json")
    for node in document["nodes"]:
        if node["node_id"] == "crop":
            node["parameters"]["source"]["bounds"] = members
    inputs = {
        "file": publish(
            service.storage, ply(b"1 2 3\n1 3 3\n9 9 3\n2 2 3\n2 3 3\n", count=5)
        )
    }
    if source == "input":
        inputs["roi"] = root
    registry, _ = build_chain()
    try:
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=WorkflowGraphTemplate.model_validate(document),
            input_values=inputs,
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=configured,
            ),
        )
        assert result.outputs["found"] == {"value": True}
        display = GeometryPreview.model_validate(result.outputs["body"]["geometry"])
        assert {roi.roi_id for roi in display.rois} == {"all", "left", "right"}
        restored_contract = CropCloudParameters(roi_id="all", rois=display.rois)
        assert restored_contract.rois[0].kind == "union"
        malformed = display.model_dump(mode="json")
        malformed["rois"][0]["geometry"]["roi_ids"].append("unused")
        with pytest.raises(ValueError):
            GeometryPreview.model_validate(malformed)
        cloud = CloudReference.model_validate(result.outputs["cropped"])
        with runtime.borrow(cloud) as view:
            np.testing.assert_array_equal(
                np.concatenate([view.source_indices(i, i + 2) for i in (0, 2)]),
                [0, 1, 3, 4],
            )
        assert runtime.source_point_count(cloud) == 5
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_union_asset_recovers_recipe_fields_and_original_rows(tmp_path):
    """关闭原 Scope 后读取新资产，保留全部字段及不可变方法快照。"""
    service = create_resource_service(tmp_path)
    points = np.array([[0, 0, 0], [3, 0, 0], [5, 0, 0], [0, 0, 0]], dtype=np.float32)
    labels = np.array([2**64 - 1, 2**63, 7, 8], dtype=np.uint64)
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=points, attributes=(("label", labels, "1"),)
    )
    other = ResourceScope(kind="workflow")
    target = get_cloud_runtime(other, run_id="restored-union", policy=policy())
    limits = CloudAssetPolicy(
        max_asset_bytes=65536, max_archive_bytes=131072, chunk_bytes=128
    )
    config = parameters(union("all", "left", "right"), *boxes())
    try:
        result, _ = crop_roi(runtime, cloud, config, cancel=lambda: None)
        saved = save_cloud(
            runtime,
            result,
            service=service,
            project_id="test",
            name="Union",
            mode="derived",
            write_identity="e" * 64,
            policy=limits,
            cancel=lambda: None,
        )
        document = service.read(saved, project_id="test")
        assert (
            document.content.point_cloud.provenance.method == result.provenance.method
        )
        assert not scope.close() and runtime.budget.used == 0
        restored = read_asset(
            target,
            saved,
            service=service,
            project_id="test",
            policy=limits,
            cancel=lambda: None,
        )
        assert restored.run_id == "restored-union"
        # 资产保留方法快照；新运行引用不能冒充原运行的派生关系。
        assert restored.provenance.method is None and restored.provenance.parents == ()
        assert restored.source.reference == saved
        assert (
            service.read(saved, project_id="test").content.point_cloud.provenance.method
            == result.provenance.method
        )
        assert target.source_point_count(restored) == 4
        with target.borrow(restored) as view:
            for start in (0, 2):
                stop = min(start + 2, 3)
                selected = [0, 2, 3][start:stop]
                np.testing.assert_array_equal(
                    view.source_indices(start, stop), selected
                )
                np.testing.assert_array_equal(
                    view.chunk(start, stop)["positions"], points[selected]
                )
                np.testing.assert_array_equal(
                    view.chunk(start, stop)["label"][:, 0], labels[selected]
                )
    finally:
        assert not scope.close()
        assert not other.close() and target.budget.used == 0
