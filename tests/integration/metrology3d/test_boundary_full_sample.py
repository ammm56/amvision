"""完整现场文件与 M3.2 内核组合；不冒充节点发布、测量准确度或生产验收。"""

from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.workflows.point_cloud.runtime import CloudRuntime
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from custom_nodes._metrology3d_nodes.shared.boundary_fitting import (
    evaluate_fit_quality,
    fit_boundary_circle,
    fit_boundary_line,
)
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.extract_boundary import (
    extract_boundary_array,
)
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters
from tests.point_cloud_support import options, policy
from tests.test_metrology3d_boundary_contracts import (
    circle_parameters,
    evaluation,
    line_parameters,
)


def test_complete_sample_kernel_sources_precision_and_release(tmp_path, request):
    """全文件读取后才取显式测试 ROI，边界算法不使用显示采样。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须显式提供")
    started = monotonic()
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    with Path(supplied).open("rb") as stream:
        meta = storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert meta.content_length == 479677235
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
    runtime = CloudRuntime(run_id="m32-complete-sample-kernels", policy=limits)
    try:
        cloud = read_file_reference(
            runtime=runtime,
            object_store=storage,
            project_id="test",
            file=file,
            options=options(),
            cancel=lambda: None,
        )
        assert cloud.point_count == 14745099
        digest = sha256()
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, limits.chunk_rows):
                data = view.chunk(
                    start, min(start + limits.chunk_rows, cloud.point_count)
                )["positions"]
                assert data.dtype == np.dtype("float32")
                digest.update(data)
            data = None
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
            center = (
                view.chunk(middle, middle + 1)["positions"][0].astype(float).tolist()
            )
        # 当前工件只作数据链路核对；人工圆柱窗口的边界不是工件上的实际孔径。
        region = dict(
            roi_id="test-window",
            rois=[
                dict(
                    roi_id="test-window",
                    kind="cylinder",
                    frame_id="fixture",
                    length_unit="mm",
                    geometry=dict(center=center, axis=[0, 0, 1], radius=0.3, length=1),
                )
            ],
        )
        cropped, _ = crop_roi(
            runtime, filtered, CropCloudParameters(**region), cancel=lambda: None
        )
        assert 3 < cropped.point_count < 1000
        with runtime.borrow(cropped) as view:
            points = view.chunk(0, cropped.point_count)["positions"].copy()
            source_rows = view.source_indices(0, cropped.point_count).copy()
        snapshot = points.tobytes()
        parameters = extract_parameters(
            evaluation=evaluation(origin=center),
            region=region,
            surface=dict(
                alpha_radius=0.08,
                max_edge_length=0.15,
                max_normal_step=0.1,
                min_projected_area=1e-8,
            ),
            targets=[
                dict(
                    segment_id="window-edge", region=region, closed=True, role="unknown"
                )
            ],
        )
        projected = extract_boundary_array(
            points,
            parameters,
            max_working_bytes=limits.max_working_bytes,
            cancel=lambda: None,
        )
        assert projected.reason is None, projected.reason
        with runtime.borrow(cloud) as view:
            for parent_row, xyz in zip(
                source_rows[projected.source_rows], projected.positions
            ):
                np.testing.assert_array_equal(
                    view.chunk(int(parent_row), int(parent_row) + 1)["positions"][0],
                    xyz,
                )
        circle = fit_boundary_circle(
            projected.positions,
            projected.topology,
            circle_parameters(
                selection=dict(feature_id="boundary", segment_ids=["window-edge"]),
                evaluation=evaluation(origin=center),
            ),
            max_working_bytes=limits.max_working_bytes,
            cancel=lambda: None,
        )
        assert circle.reason is None, circle.reason
        assert 0 < circle.geometry["radius"] < 0.3
        sections = []
        for sign in (1, -1):
            params = extract_parameters(
                evaluation=evaluation(origin=center),
                region=region,
                surface=parameters.surface,
                method=dict(
                    kind="section",
                    origin=center,
                    normal=[sign, 0, 0],
                    numeric_tolerance=1e-9,
                ),
                targets=[
                    dict(segment_id="section", region=region, closed=False, role="open")
                ],
            )
            result = extract_boundary_array(
                points,
                params,
                max_working_bytes=limits.max_working_bytes,
                cancel=lambda: None,
            )
            assert result.reason is None, result.reason
            np.testing.assert_allclose(
                result.positions,
                (
                    points[result.source_edges].astype(float)
                    * result.weights[..., None]
                ).sum(axis=1),
                atol=1e-10,
                rtol=0,
            )
            sections.append(result)
        np.testing.assert_allclose(
            sections[0].positions, sections[1].positions, atol=1e-10, rtol=0
        )
        line = fit_boundary_line(
            sections[0].positions,
            sections[0].topology,
            line_parameters(
                selection=dict(feature_id="boundary", segment_ids=["section"]),
                evaluation=evaluation(
                    origin=center, rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]]
                ),
                positive_direction=[0, 1, 0],
            ),
            max_working_bytes=limits.max_working_bytes,
            cancel=lambda: None,
        )
        assert line.reason is None, line.reason
        line_quality = evaluate_fit_quality(
            line, line_parameters(), observation_id="sample"
        )
        # 该真实局部截线有起伏；不得把纯求解成功写成通过测试配方的 RMS 质量。
        assert not line_quality.usable
        assert any(
            item.item_id == "rms" and item.valid and not item.passed
            for item in line_quality.checks
        )
        assert points.tobytes() == snapshot and points.dtype == np.dtype("float32")
        # 同一完整输入进入实际运行引用，跨运行保存重读后仍使用完整支持拟合。
        from dataclasses import replace
        from backend.service.application.workflows.documents.measurement_resources import (
            MeasurementResourceService,
        )
        from custom_nodes._metrology3d_nodes.shared.boundary_runtime import (
            extract_boundary,
        )
        from custom_nodes._metrology3d_nodes.shared.cloud_assets import (
            save_cloud,
            read_asset,
        )
        from custom_nodes._metrology3d_nodes.shared.boundary_assets import (
            restore_boundary,
        )
        from custom_nodes._metrology3d_nodes.shared.fit_boundary import fit_boundary
        from tests.test_point_cloud_assets import POLICY

        service = MeasurementResourceService(storage)
        asset_policy = replace(
            POLICY,
            max_asset_bytes=1_000_000,
            max_archive_bytes=2_000_000,
            chunk_bytes=4096,
        )
        for label, extract_params, fit_params in (
            (
                "projection",
                parameters,
                circle_parameters(
                    selection=dict(feature_id="boundary", segment_ids=["window-edge"]),
                    evaluation=evaluation(origin=center),
                ),
            ),
            (
                "section",
                params,
                line_parameters(
                    selection=dict(feature_id="boundary", segment_ids=["section"]),
                    evaluation=evaluation(
                        origin=center, rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]]
                    ),
                    positive_direction=[0, 1, 0],
                ),
            ),
        ):
            features = extract_boundary(
                runtime, filtered, extract_params, cancel=lambda: None
            )
            assert features.items[0].valid
            expected = fit_boundary(
                runtime, features, fit_params, cancel=lambda: None
            ).items[0]
            asset = save_cloud(
                runtime,
                features.items[0].support,
                features=features,
                service=service,
                project_id="test",
                name=label,
                mode="derived",
                write_identity=sha256(label.encode()).hexdigest(),
                policy=asset_policy,
                cancel=lambda: None,
            )
            restored_runtime = CloudRuntime(run_id="restore-" + label, policy=limits)
            try:
                restored = read_asset(
                    restored_runtime,
                    asset,
                    service=service,
                    project_id="test",
                    policy=asset_policy,
                    cancel=lambda: None,
                )
                recovered = restore_boundary(
                    restored,
                    service.read(asset, project_id="test").content.point_cloud.boundary,
                )
                actual = fit_boundary(
                    restored_runtime, recovered, fit_params, cancel=lambda: None
                ).items[0]
                assert (actual.valid, actual.reason, actual.geometry) == (
                    expected.valid,
                    expected.reason,
                    expected.geometry,
                )
                assert actual.quality.metrics.items == expected.quality.metrics.items
                if label == "section":
                    assert not actual.valid and actual.geometry is None
            finally:
                restored_runtime.close()
                assert restored_runtime.budget.used == 0
        report = dict(
            input_bytes=meta.content_length,
            input_points=cloud.point_count,
            roi_points=len(points),
            projected_points=projected.topology.point_count,
            section_points=sections[0].topology.point_count,
            roi_boundary_fit_radius=circle.geometry["radius"],
            section_line_rms=line.metrics["rms"],
            section_line_quality_usable=line_quality.usable,
            elapsed_seconds=monotonic() - started,
            live_array_bytes=runtime.budget.used,
        )
        print(json.dumps(report), flush=True)
    finally:
        runtime.close()
        assert runtime.budget.used == 0
