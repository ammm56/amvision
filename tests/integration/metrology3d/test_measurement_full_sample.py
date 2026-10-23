"""完整现场文件的真实测量图；自一致性不冒充工件标定真值。"""

from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest

from backend.contracts.workflows.geometry3d import FitPlaneParameters
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from tests.integration.metrology3d.test_measurement_nodes import measurement_graph
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_measurement_contracts import (
    height_parameters,
    measurement_policy,
)
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preview import preview_policy, decode


def test_complete_file_height_step_evidence_and_release(tmp_path, request):
    """全输入严格读取，原行号/dtype 不变；同一局部面的高度应为零。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须显式提供")
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
    limits = policy(
        max_header_bytes=65536,
        max_decoded_bytes=400000000,
        max_working_bytes=134217728,
        chunk_rows=65536,
        chunk_bytes=4194304,
        max_live_array_bytes=800000000,
    )
    preview = preview_policy(
        max_points=10000,
        max_data_bytes=1000000,
        max_body_bytes=4000000,
        max_working_bytes=134217728,
    )
    configured = execution_policy().model_copy(
        update={"io": limits, "preview": preview}
    )
    metadata = dict(project_id="test", workflow_run_id="m3-height-complete")
    scope = get_or_create_workflow_resource_scope(metadata)
    runtime = get_cloud_runtime(
        scope, run_id=metadata["workflow_run_id"], policy=limits
    )
    try:
        cloud = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=file,
            options=options(),
            cancel=lambda: None,
        )
        assert cloud.point_count == 14745099
        digest = sha256()
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, limits.chunk_rows):
                points = view.chunk(
                    start, min(start + limits.chunk_rows, cloud.point_count)
                )["positions"]
                assert points.dtype == np.dtype("float32")
                digest.update(points.tobytes())
            points = None
        assert (
            digest.hexdigest()
            == "956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6"
        )
        filtered, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=["positions"], sentinels=[]),
            cancel=lambda: None,
        )
        with runtime.borrow(filtered) as view:
            middle = filtered.point_count // 2
            query = (
                view.chunk(middle, middle + 1)["positions"][0].astype(float).tolist()
            )
        # 以下仅为该样本的局部自一致性测试配置，不进入生产配方。
        fit = plane_parameters(feature_id="target").model_dump(mode="json")
        for rule in fit["quality_policy"]["rules"]:
            if rule["item_id"] == "rms":
                rule["upper"] = 0.05
            if rule["item_id"] == "max_residual":
                rule["upper"] = 0.1
        p = height_parameters(
            query_position=query,
            search_radius=0.3,
            search_interval=(-0.5, 0.5),
            support_radius=0.3,
            plane_fit=FitPlaneParameters.model_validate(fit),
            quality_policy=measurement_policy(
                reference_nearest_distance={"upper": 0.1},
                target_nearest_distance={"upper": 0.1},
                reference_triangle_edge={"upper": 0.15},
                target_triangle_edge={"upper": 0.15},
                reference_max_residual={"upper": 0.1},
                target_max_residual={"upper": 0.1},
            ),
        )
        roi = dict(
            roi_id="patch",
            kind="cylinder",
            frame_id="fixture",
            length_unit="mm",
            geometry=dict(center=query, axis=[0, 0, 1], radius=0.3, length=1),
        )
        graph = measurement_graph(height=p, reference_roi=roi, read=False)
        for node in graph.nodes:
            if node.node_id == "preview":
                node.parameters["point_limit"] = 10000
        registry, _ = build_chain()
        result = WorkflowGraphExecutor(registry=registry).execute(
            template=graph,
            input_values={
                f"cloud-{name}": filtered.model_dump(mode="json")
                for name in ("reference", "height", "preview")
            },
            execution_metadata=metadata,
            runtime_context=WorkflowServiceNodeRuntimeContext(
                session_factory=None,
                dataset_storage=service.storage,
                point_cloud_policy=configured,
            ),
        )
        evidence = MeasurementEvidence3d.model_validate(result.outputs["evidence"])
        item = evidence.items[0]
        assert item.valid, item.model_dump_json()
        assert abs(item.value) < 1e-9
        assert abs(result.outputs["step"]["items"][0]["value"]) < 1e-9
        for side in item.support:
            assert side.source_point_count == 14745099
            for index, xyz in zip(side.coverage.source_indices, side.coverage.triangle):
                with runtime.borrow(cloud) as view:
                    np.testing.assert_array_equal(
                        view.chunk(index, index + 1)["positions"][0], xyz
                    )
        display = result.outputs["body"]
        assert display["state"] == "ready" and display["display_point_count"] == 10000
        assert decode(display)["positions"].dtype == np.dtype("float32")
        report = dict(
            input_bytes=meta.content_length,
            input_points=cloud.point_count,
            query=query,
            height=item.value,
            elapsed_seconds=monotonic() - started,
            live_array_bytes=runtime.budget.used,
        )
        destination = request.config.getoption("--cloud-report-dir")
        if destination:
            directory = Path(destination)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "m3-height-preview.json").write_text(
                json.dumps(display), encoding="utf-8"
            )
            (directory / "m3-height-parameters.json").write_text(
                p.model_dump_json(), encoding="utf-8"
            )
            (directory / "m3-height-report.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
        print(json.dumps(report), flush=True)
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
