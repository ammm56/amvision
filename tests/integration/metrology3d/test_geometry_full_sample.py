"""完整现场样本验证数据、几何和资源链路，不将未标定工件当尺寸真值。"""

from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest

from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    FilterCloudValid,
)
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from tests.integration.metrology3d.test_geometry_nodes import geometry_graph
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.test_metrology3d_preview import preview_policy, decode
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_frame import frame_parameters
from tests.test_metrology3d_plane import plane_parameters


@pytest.mark.parametrize("algorithm", ["svd", "ransac-svd"])
def test_complete_sample_geometry_and_release(tmp_path, request, algorithm):
    """全样本、全行读取与变换；质量阈值仅检查测试链路可执行性。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须由 --cloud-sample 显式提供")
    started = monotonic()
    service = create_resource_service(tmp_path)
    with Path(supplied).open("rb") as stream:
        meta = service.storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert (
        meta.checksum
        == "ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b"
    )
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=meta.object_key,
        file_name="sample.ply",
        media_type=meta.media_type,
        content_length=meta.content_length,
        checksum_algorithm="sha256",
        checksum=meta.checksum,
        immutable_version=meta.immutable_version,
    )
    metadata = dict(project_id="test", workflow_run_id="m2-full-sample")
    scope = get_or_create_workflow_resource_scope(metadata)
    limits = policy(
        max_header_bytes=65536,
        max_decoded_bytes=400000000,
        # 原生全样本用例按既有最坏候选估算显式配置，不作为生产容量。
        max_working_bytes=34359738368 if algorithm == "ransac-svd" else 134217728,
        chunk_rows=65536,
        chunk_bytes=4194304,
        max_live_array_bytes=800000000,
    )
    runtime = get_cloud_runtime(scope, run_id="m2-full-sample", policy=limits)

    def cancel():
        """完整样本正常路径不注入取消。"""

    try:
        # mm/右手仅为显式测试坐标声明，不声称此未标定样本具备可追溯物理精度。
        cloud = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=file,
            options=options(),
            cancel=cancel,
        )
        assert cloud.point_count == 14745099
        digest = sha256()
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, limits.chunk_rows):
                block = view.chunk(
                    start, min(start + limits.chunk_rows, cloud.point_count)
                )["positions"]
                digest.update(block.tobytes())
            block = None
        assert (
            digest.hexdigest()
            == "956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6"
        )
        filtered, summary = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=["positions"], sentinels=[]),
            cancel=cancel,
        )
        assert summary["kept_count"] > 0
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        with runtime.borrow(filtered) as view:
            for start in range(0, filtered.point_count, limits.chunk_rows):
                block = view.chunk(
                    start, min(start + limits.chunk_rows, filtered.point_count)
                )["positions"]
                low = np.minimum(low, block.min(axis=0))
                high = np.maximum(high, block.max(axis=0))
            block = None
        assert np.all(high > low)
        roi = dict(
            roi_id="all",
            frame_id="fixture",
            length_unit="mm",
            kind="box",
            geometry=dict(
                center=((high + low) / 2).tolist(),
                size=(high - low).tolist(),
                rotation=np.eye(3).tolist(),
            ),
        )
        p = plane_parameters(feature_id="primary").model_dump(mode="json")
        if algorithm == "ransac-svd":
            # 未标定工件不提供生产公差；全包围盒直径仅用于全点原生容量链路。
            # 外点选择精度由独立解析真值用例验证，而不是用本配置声称测量合格。
            p["algorithm"] = dict(
                kind="ransac-svd",
                distance_threshold=float(np.linalg.norm(high - low)),
                sample_size=3,
                iterations=100,
                probability=0.999,
            )
        for rule in p["quality_policy"]["rules"]:
            if rule["item_id"] in {"rms", "max_residual"}:
                rule["upper"] = 1000000
            elif rule["item_id"] in {"tangent_ratio", "normal_gap"}:
                rule["lower"] = 1e-12
        registry, _ = build_chain()
        graph = geometry_graph(
            roi,
            p,
            frame_parameters(
                origin=dict(kind="anchor-projection", anchor=[0, 0, 0])
            ).model_dump(mode="json"),
            read=False,
            preview=True,
        )
        for node in graph.nodes:
            if node.node_id == "preview":
                node.parameters["point_limit"] = 10000
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=graph,
            input_values={"cloud": filtered.model_dump(mode="json")},
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=execution_policy().model_copy(
                    update={
                        "io": limits,
                        "preview": preview_policy(
                            max_points=10000,
                            max_data_bytes=1000000,
                            max_body_bytes=2000000,
                            max_working_bytes=134217728,
                        ),
                    }
                ),
            ),
        )
        assert len(result.node_records) == 5
        display = result.outputs["body"]
        assert display["state"] == "ready" and display["display_point_count"] == 10000
        assert decode(display)["positions"].dtype == np.dtype("float32")
        (tmp_path / "geometry-preview.json").write_text(
            json.dumps(display), encoding="utf-8"
        )
        crop = CloudReference.model_validate(result.outputs["cropped"])
        features = Features3d.model_validate(result.outputs["features"])
        pose = Pose3d.model_validate(result.outputs["pose"])
        transformed = CloudReference.model_validate(result.outputs["cloud"])
        assert crop.point_count == filtered.point_count
        assert features.items[0].valid, features.items[0].reason
        assert pose.state == "found", pose.reason
        assert (
            transformed.point_count == crop.point_count
            and transformed.fields == cloud.fields
        )
        assert runtime.source_point_count(transformed) == cloud.point_count
        rotation = np.asarray(pose.transform.matrix)[:3, :3]
        translation = np.asarray(pose.transform.matrix)[:3, 3]
        with runtime.borrow(transformed) as result, runtime.borrow(crop) as original:
            for start in range(0, crop.point_count, limits.chunk_rows):
                stop = min(start + limits.chunk_rows, crop.point_count)
                xyz = result.chunk(start, stop)["positions"]
                source = original.chunk(start, stop)["positions"]
                assert xyz.dtype == np.float32 and np.isfinite(xyz).all()
                reconstructed = (xyz.astype(np.float64) - translation) @ rotation
                magnitude = max(
                    1.0, float(np.max(np.abs(source))), float(np.max(np.abs(xyz)))
                )
                np.testing.assert_allclose(
                    reconstructed,
                    source,
                    rtol=0,
                    atol=8 * np.finfo(np.float32).eps * magnitude,
                )
                np.testing.assert_array_equal(
                    result.source_indices(start, stop),
                    original.source_indices(start, stop),
                )
            xyz = source = reconstructed = None
        print(
            dict(
                algorithm=algorithm,
                points=cloud.point_count,
                valid_points=crop.point_count,
                dtype="float32",
                seconds=round(monotonic() - started, 3),
                retained_bytes=runtime.budget.used,
            )
        )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
